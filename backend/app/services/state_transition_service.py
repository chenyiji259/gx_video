"""状态机服务。

来源文档：doc 04 §2（设计原则）、§4（项目状态机）、§5（任务状态机）、§6（镜头状态机）、§20.4（失效规则）

职责：
  作为系统内所有状态变更的唯一入口，防止状态逻辑散落到各个 Agent / Service / Tool。
  任何代码需要改变 project.current_stage、AgentTask.status、ToolJob.status，
  都必须通过本 Service，不得直接 ORM 赋值后 commit。

核心方法：
  advance_project()     — 项目阶段推进（含合法性校验 + 事件发送）
  transition_agent_task() — AgentTask 状态切换
  transition_tool_job()   — ToolJob 状态切换（含 retry_count 管理）
  mark_stale()          — 上游变更触发的下游失效传播

strict mode（来自 workflow.yaml）：
  True  → 非法迁移抛 StateTransitionError
  False → 非法迁移仅记录 warning（允许强制修复数据）

注意：所有方法接受外部 AsyncSession，不自行开 UoW。
调用方负责在同一事务内完成业务数据写入 + 状态变更 + 事件发送。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.logging import get_logger
from app.domain.states import (
    ALLOWED_AGENT_TASK_TRANSITIONS,
    ALLOWED_PROJECT_TRANSITIONS,
    ALLOWED_TOOL_JOB_TRANSITIONS,
    ProjectStage,
    StaleScope,
    TaskStatus,
)
from app.models.project import Project
from app.models.workflow import AgentTask, ToolJob
from app.schemas.event import ProjectEvent

_logger = get_logger("services.state_transition", layer="system")


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class StateTransitionError(Exception):
    """非法状态迁移异常。

    在 strict mode 下，任何违反 ALLOWED_*_TRANSITIONS 规则的迁移都会抛此异常。
    """

    def __init__(
        self,
        message: str,
        *,
        from_state: str,
        to_state: str,
        entity_type: str,
        entity_id: str,
    ) -> None:
        super().__init__(message)
        self.from_state = from_state
        self.to_state = to_state
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.code = "illegal_state_transition"


# ---------------------------------------------------------------------------
# 状态机服务
# ---------------------------------------------------------------------------

class StateTransitionService:
    """状态机服务（无状态，每次调用传入 session）。

    建议作为模块级单例使用（无实例状态，线程安全）。
    """

    def __init__(self) -> None:
        cfg = get_config().workflow
        self._strict: bool = cfg.state_machine_strict

    # ------------------------------------------------------------------ #
    # 项目阶段推进
    # ------------------------------------------------------------------ #

    async def advance_project(
        self,
        session: AsyncSession,
        project: Project,
        to_stage: ProjectStage | str,
        *,
        emit_event: bool = True,
        correlation_id: str | None = None,
    ) -> Project:
        """推进项目到指定阶段（含合法性校验）。

        Args:
            session:        调用方的 AsyncSession。
            project:        已加载的 Project ORM 对象。
            to_stage:       目标阶段（ProjectStage enum 或等价字符串）。
            emit_event:     是否通过 EventLogService 发送事件（默认 True）。
            correlation_id: 追踪 ID，透传到事件。

        Returns:
            更新后的 Project 对象（stage 已变更，等待外层 commit）。

        Raises:
            StateTransitionError: strict mode 下非法迁移。
        """
        _logger.info(
            f"[ADVANCE_PROJECT] 进入: project_id={project.id}, current_stage={project.current_stage}, to_stage={to_stage}, emit_event={emit_event}",
            event_type="advance_project_enter",
        )

        to_stage = ProjectStage(to_stage)
        from_stage = ProjectStage(project.current_stage)

        allowed = ALLOWED_PROJECT_TRANSITIONS.get(from_stage, frozenset())
        _logger.info(
            f"[ADVANCE_PROJECT] 迁移检查: {from_stage.value!r} → {to_stage.value!r}, allowed={allowed}",
            event_type="advance_project_transition_check",
        )

        if to_stage not in allowed:
            msg = (
                f"项目 {project.id!r} 非法阶段迁移: "
                f"{from_stage.value!r} → {to_stage.value!r}"
            )
            if self._strict:
                _logger.error(f"[ADVANCE_PROJECT] 非法迁移，strict模式，抛出异常: {msg}", event_type="advance_project_illegal_transition_error")
                raise StateTransitionError(
                    msg,
                    from_state=from_stage.value,
                    to_state=to_stage.value,
                    entity_type="project",
                    entity_id=project.id,
                )
            _logger.warning(msg, event_type="illegal_stage_transition")

        project.current_stage = to_stage.value
        session.add(project)
        _logger.info(
            f"[ADVANCE_PROJECT] project.current_stage 已更新为 {to_stage.value!r}",
            event_type="advance_project_stage_updated",
        )

        _logger.info(
            f"Project {project.id!r} stage: {from_stage.value!r} → {to_stage.value!r}",
            event_type="project_stage_advanced",
        )

        if emit_event:
            _logger.info("[ADVANCE_PROJECT] 准备调用 event_log_service.emit", event_type="advance_project_emit_start")
            from app.services.event_log_service import event_log_service
            try:
                await event_log_service.emit(
                    session,
                    ProjectEvent(
                        project_id=project.id,
                        aggregate_type="project",
                        aggregate_id=project.id,
                        event_type=f"project_{to_stage.value}",
                        category="domain",
                        payload={
                            "from_stage": from_stage.value,
                            "to_stage": to_stage.value,
                        },
                        correlation_id=correlation_id,
                    ),
                )
                _logger.info("[ADVANCE_PROJECT] event_log_service.emit 完成", event_type="advance_project_emit_done")
            except Exception as emit_exc:
                _logger.error(f"[ADVANCE_PROJECT] event_log_service.emit 异常: {emit_exc!r}", event_type="advance_project_emit_error")
                raise

        _logger.info("[ADVANCE_PROJECT] 准备返回 project", event_type="advance_project_exit")
        return project

    # ------------------------------------------------------------------ #
    # AgentTask 状态切换
    # ------------------------------------------------------------------ #

    async def transition_agent_task(
        self,
        session: AsyncSession,
        task: AgentTask,
        to_status: TaskStatus | str,
        *,
        output_ref: dict[str, Any] | None = None,
        error_payload: dict[str, Any] | None = None,
    ) -> AgentTask:
        """切换 AgentTask 状态。

        Args:
            session:       调用方的 AsyncSession。
            task:          已加载的 AgentTask ORM 对象。
            to_status:     目标状态。
            output_ref:    成功时写入的输出引用（版本 ID 等）。
            error_payload: 失败时写入的错误信息。

        Returns:
            更新后的 AgentTask 对象。

        Raises:
            StateTransitionError: strict mode 下非法迁移。
        """
        to_status = TaskStatus(to_status)
        from_status = TaskStatus(task.status)

        allowed = ALLOWED_AGENT_TASK_TRANSITIONS.get(from_status, frozenset())
        if to_status not in allowed:
            msg = (
                f"AgentTask {task.id!r} 非法状态迁移: "
                f"{from_status.value!r} → {to_status.value!r}"
            )
            if self._strict:
                raise StateTransitionError(
                    msg,
                    from_state=from_status.value,
                    to_state=to_status.value,
                    entity_type="agent_task",
                    entity_id=task.id,
                )
            _logger.warning(msg, event_type="illegal_task_transition")

        task.status = to_status.value
        if output_ref is not None:
            task.output_ref = output_ref
        if error_payload is not None:
            task.error_payload = error_payload

        session.add(task)

        _logger.debug(
            f"AgentTask {task.id!r} status: {from_status.value!r} → {to_status.value!r}",
            event_type="agent_task_transitioned",
        )
        return task

    # ------------------------------------------------------------------ #
    # ToolJob 状态切换
    # ------------------------------------------------------------------ #

    async def transition_tool_job(
        self,
        session: AsyncSession,
        job: ToolJob,
        to_status: TaskStatus | str,
        *,
        output_payload: dict[str, Any] | None = None,
        error_info: dict[str, Any] | None = None,
        increment_retry: bool = False,
    ) -> ToolJob:
        """切换 ToolJob 状态（含 retry_count 管理）。

        Args:
            session:          调用方的 AsyncSession。
            job:              已加载的 ToolJob ORM 对象。
            to_status:        目标状态。
            output_payload:   成功时写入的工具输出。
            error_info:       失败时写入的错误信息（存入 output_payload）。
            increment_retry:  是否递增 retry_count（进入 retrying 时传 True）。

        Returns:
            更新后的 ToolJob 对象。

        Raises:
            StateTransitionError: strict mode 下非法迁移。
        """
        to_status = TaskStatus(to_status)
        from_status = TaskStatus(job.status)

        allowed = ALLOWED_TOOL_JOB_TRANSITIONS.get(from_status, frozenset())
        if to_status not in allowed:
            msg = (
                f"ToolJob {job.id!r} 非法状态迁移: "
                f"{from_status.value!r} → {to_status.value!r}"
            )
            if self._strict:
                raise StateTransitionError(
                    msg,
                    from_state=from_status.value,
                    to_state=to_status.value,
                    entity_type="tool_job",
                    entity_id=job.id,
                )
            _logger.warning(msg, event_type="illegal_tool_job_transition")

        job.status = to_status.value
        if output_payload is not None:
            job.output_payload = output_payload
        if error_info is not None:
            # CLASS-04 修复：错误信息写入独立 error_payload，不覆盖 output_payload
            job.error_payload = error_info
        if increment_retry:
            job.retry_count = (job.retry_count or 0) + 1

        session.add(job)

        _logger.debug(
            f"ToolJob {job.id!r} status: {from_status.value!r} → {to_status.value!r} "
            f"(retry={job.retry_count})",
            event_type="tool_job_transitioned",
        )
        return job

    # ------------------------------------------------------------------ #
    # Stale 失效传播
    # ------------------------------------------------------------------ #

    async def mark_stale(
        self,
        session: AsyncSession,
        project: Project,
        scope: StaleScope | str,
        *,
        shot_id: str | None = None,
    ) -> Project:
        """根据上游变更范围标记下游产物为 stale，并回退项目阶段。

        实现策略（doc 04 §20.4）：
          AUDIO_CHANGED        → 项目退到 input_ready，所有 shots stale
          BRIEF_CHANGED        → 项目退到 audio_analyzed，所有 shots stale
          STYLE_CHANGED        → 项目退到 shot_plan_ready，所有 shots stale
          SINGLE_SHOT_CHANGED  → 只有指定 shot stale（需传 shot_id），项目退到 clips_ready

        shots 表的 SQL UPDATE 通过 sqlalchemy.text() 执行，不依赖 Shot ORM，
        后续 tasks 9-01 shots 表建好后该语句即生效。

        Args:
            session:   调用方的 AsyncSession。
            project:   已加载的 Project ORM 对象。
            scope:     失效范围枚举。
            shot_id:   SINGLE_SHOT_CHANGED 时必传，指定被修改的 shot ID。

        Returns:
            更新后的 Project 对象（stage 已退回，等待外层 commit）。
        """
        scope = StaleScope(scope)

        if scope == StaleScope.AUDIO_CHANGED:
            target_stage = ProjectStage.INPUT_READY
            await self._mark_all_shots_stale(session, project.id)

        elif scope == StaleScope.BRIEF_CHANGED:
            target_stage = ProjectStage.AUDIO_ANALYZED
            await self._mark_all_shots_stale(session, project.id)

        elif scope == StaleScope.STYLE_CHANGED:
            target_stage = ProjectStage.SHOT_PLAN_READY
            await self._mark_all_shots_stale(session, project.id)

        elif scope == StaleScope.SINGLE_SHOT_CHANGED:
            if not shot_id:
                raise ValueError(
                    "mark_stale(SINGLE_SHOT_CHANGED) 必须传入 shot_id"
                )
            target_stage = ProjectStage.CLIPS_READY
            await self._mark_single_shot_stale(session, shot_id)

        else:
            raise ValueError(f"未知 StaleScope: {scope!r}")

        # 项目阶段回退：阶段变更本身是领域事实，应当发事件通知前端更新 Pipeline 显示
        # （stale 标记是内部实现细节，不单独发事件；阶段回退事件由 advance_project 发）
        project = await self.advance_project(
            session,
            project,
            target_stage,
            emit_event=True,
        )

        _logger.info(
            f"Project {project.id!r} stale: scope={scope.value!r} → stage={target_stage.value!r}",
            event_type="project_stale_marked",
        )
        return project

    # ------------------------------------------------------------------ #
    # 公共辅助：仅 stale 不做阶段回退
    # ------------------------------------------------------------------ #

    async def mark_shot_stale_only(
        self,
        session: AsyncSession,
        shot_id: str,
    ) -> None:
        """将单个 shot 及其 active clip 标记 stale，**不触发项目阶段回退**。

        使用场景（doc 04 §6.3）：
          shot 被语义修改时，若项目尚处于 shot_plan_ready / storyboard_ready 等
          "无 clip" 阶段，mark_stale(SINGLE_SHOT_CHANGED) 会尝试将项目推进到
          CLIPS_READY，引发非法阶段跳转。
          本方法只做失效标记，不改变项目阶段。

        Args:
            session: 调用方的 AsyncSession（外层 UoW 事务中）。
            shot_id: 要标记 stale 的 shot ID。
        """
        await self._mark_single_shot_stale(session, shot_id)
        _logger.info(
            f"Shot {shot_id!r} 已标记 stale（无阶段回退）",
            event_type="shot_stale_marked_no_regression",
        )

    # ------------------------------------------------------------------ #
    # 批次C：角色参考图变更 stale 传播
    # ------------------------------------------------------------------ #

    async def mark_character_ref_changed_stale(
        self,
        session: AsyncSession,
        project: Project,
        character_id: str,
    ) -> Project:
        """角色参考图重新生成后，标记使用该角色的所有 shot + active clip stale，
        并将项目阶段回退到 visual_bible_ready（若当前阶段已超过该节点）。

        依据：doc11 §3.3 失效规则 —— 修改角色参考图 → visual_bible_ready
        使用 raw SQL（不依赖 Shot ORM），ProgrammingError 时静默跳过。

        Args:
            session:      调用方的 AsyncSession。
            project:      已加载的 Project ORM 对象。
            character_id: 变更的角色 ID（对应 shots.character_binding JSON 中的 character_id）。

        Returns:
            更新后的 Project 对象（阶段已退回，等待外层 commit）。
        """
        await self._mark_shots_by_character_stale(session, project.id, character_id)

        # 只在阶段已超过 visual_bible_ready 时才触发回退
        _SHOULD_REGRESS = {
            ProjectStage.SHOT_PLAN_READY,
            ProjectStage.STORYBOARD_READY,
            ProjectStage.CLIPS_READY,
            ProjectStage.TIMELINE_READY,
            ProjectStage.EXPORT_READY,
            ProjectStage.COMPLETED,
        }
        current = ProjectStage(project.current_stage)
        if current in _SHOULD_REGRESS:
            project = await self.advance_project(
                session,
                project,
                ProjectStage.VISUAL_BIBLE_READY,
                emit_event=True,
            )

        _logger.info(
            f"Project {project.id!r} character stale: character_id={character_id!r} "
            f"stage={project.current_stage!r}",
            event_type="character_ref_stale_marked",
        )
        return project

    # ------------------------------------------------------------------ #
    # 内部工具方法
    # ------------------------------------------------------------------ #

    async def _mark_all_shots_stale(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> None:
        """将项目的所有 shots 标记为 stale。

        使用 sqlalchemy.text() 执行原生 SQL，不依赖 Shot ORM 类，
        shots 表由 task 9-01 迁移建立后本语句即生效。
        若 shots 表尚不存在（开发中期 task 9-01 完成前），捕获 ProgrammingError
        并记录警告而不抛出，防止异常穿透事务导致历史数据回滚。
        """
        stmt = text(
            "UPDATE shots SET status = 'stale', updated_at = NOW() "
            "WHERE project_id = :project_id "
            "AND status NOT IN ('failed')"
        )
        try:
            await session.execute(stmt, {"project_id": project_id})
        except ProgrammingError:
            _logger.debug(
                f"shots 表尚未建立（task 9-01 前），_mark_all_shots_stale 跳过: "
                f"project_id={project_id!r}",
                event_type="shots_table_not_ready",
            )

    async def _mark_shots_by_character_stale(
        self,
        session: AsyncSession,
        project_id: str,
        character_id: str,
    ) -> None:
        """将所有 character_binding 包含指定 character_id 的 shot 及其 active clip 标记 stale。

        使用 PostgreSQL JSONB 数组操作；shots / clip_versions 建表前静默跳过。
        """
        match_sql = (
            "  AND ( "
            "      (jsonb_typeof(character_binding) = 'array' AND EXISTS ( "
            "          SELECT 1 FROM jsonb_array_elements(character_binding) AS elem "
            "          WHERE elem->>'character_id' = :character_id "
            "      )) "
            "      OR "
            "      (jsonb_typeof(character_binding) = 'object' AND ( "
            "          character_binding->>'character_id' = :character_id "
            "          OR EXISTS ( "
            "              SELECT 1 FROM jsonb_array_elements_text(COALESCE(character_binding->'character_ids', '[]'::jsonb)) AS elem "
            "              WHERE elem = :character_id "
            "          ) "
            "      )) "
            "  ) "
        )
        shot_stmt = text(
            "UPDATE shots SET status = 'stale', updated_at = NOW() "
            "WHERE project_id = :project_id "
            "  AND character_binding IS NOT NULL "
            + match_sql +
            "AND status NOT IN ('failed')"
        )
        clip_stmt = text(
            "UPDATE clip_versions SET status = 'stale' "
            "WHERE shot_id IN ( "
            "    SELECT id FROM shots "
            "    WHERE project_id = :project_id "
            "      AND character_binding IS NOT NULL "
            + match_sql +
            ") "
            "AND is_active = TRUE"
        )
        try:
            await session.execute(shot_stmt, {"project_id": project_id, "character_id": character_id})
            await session.execute(clip_stmt, {"project_id": project_id, "character_id": character_id})
        except ProgrammingError:
            _logger.debug(
                f"shots/clip_versions 表尚未建立，_mark_shots_by_character_stale 跳过: "
                f"project_id={project_id!r} character_id={character_id!r}",
                event_type="shots_table_not_ready",
            )

    async def _mark_single_shot_stale(
        self,
        session: AsyncSession,
        shot_id: str,
    ) -> None:
        """将指定 shot 及其关联 clip 标记为 stale。

        同样使用 raw SQL，不依赖 Shot ORM。
        shots / clip_versions 均在 task 9-01 后才建表，捕获 ProgrammingError 防止
        异常穿透。
        """
        shot_stmt = text(
            "UPDATE shots SET status = 'stale', updated_at = NOW() "
            "WHERE id = :shot_id"
        )
        clip_stmt = text(
            "UPDATE clip_versions SET status = 'stale' "
            "WHERE shot_id = :shot_id AND is_active = TRUE"
        )
        try:
            await session.execute(shot_stmt, {"shot_id": shot_id})
            await session.execute(clip_stmt, {"shot_id": shot_id})
        except ProgrammingError:
            _logger.debug(
                f"shots/clip_versions 表尚未建立（task 9-01 前），_mark_single_shot_stale 跳过: "
                f"shot_id={shot_id!r}",
                event_type="shots_table_not_ready",
            )


# ---------------------------------------------------------------------------
# 模块级单例（无实例状态，线程安全）
# ---------------------------------------------------------------------------

state_transition_service = StateTransitionService()
