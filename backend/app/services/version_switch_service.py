"""版本切换服务（Version Switch Service）。

来源文档：doc 09 任务 12-04 / doc 04 §14（回退规则）

职责：
  在版本化产物之间切换 active 指针，并执行正确的 stale 传播和项目阶段回退。
  目前支持 4 类版本切换：
    - creative_brief   → stale 传播到 shot_plan 以下，项目退到 audio_analyzed
    - style_bible      → stale 传播到 storyboard / clips / timeline，项目退到 shot_plan_ready
    - storyboard       → stale 传播到 clips / timeline，项目退到 storyboard_ready
    - timeline         → 只切换 active 指针，不影响上游

设计约束：
  - 切换只能切 active 指针 + stale 传播，不删除历史版本。
  - stale 传播遵守 docs/04 §12.2 失效传播矩阵。
  - storyboard 切换不会错误回退到 brief 或 audio 阶段。
  - timeline 切换不影响任何上游产物。
  - 所有 DB 操作通过 UoW 管理，保证原子性。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.states import ProjectStage, StaleScope
from app.models.timeline import TimelineVersion
from app.models.workflow import PendingDecision
from app.repositories.conversation_repository import ConversationSessionRepository
from app.repositories.decision_repository import DecisionRepository
from app.repositories.planning_repositories import (
    CreativeBriefRepository,
    StyleBibleRepository,
)
from app.repositories.project_repository import ProjectRepository
from app.repositories.storyboard_repositories import StoryboardVersionRepository
from app.repositories.timeline_repository import TimelineVersionRepository
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.event import ProjectEvent
from app.services.event_log_service import event_log_service
from app.services.state_transition_service import state_transition_service

_logger = get_logger("services.version_switch", layer="system")


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class VersionSwitchError(Exception):
    """版本切换业务异常。"""

    def __init__(self, message: str, code: str = "version_switch_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 支持的实体类型
# ---------------------------------------------------------------------------

SUPPORTED_ENTITY_TYPES: frozenset[str] = frozenset({
    "brief", "style", "storyboard", "timeline",
})

# storyboard 版本切换时需要退回阶段的阶段列表（比 storyboard_ready 更靠后的阶段）
_STAGES_AFTER_STORYBOARD: frozenset[str] = frozenset({
    ProjectStage.CLIPS_READY.value,
    ProjectStage.TIMELINE_READY.value,
    ProjectStage.EXPORT_READY.value,
    ProjectStage.COMPLETED.value,
})


# ---------------------------------------------------------------------------
# VersionSwitchService
# ---------------------------------------------------------------------------

class VersionSwitchService:
    """版本切换服务：切换 active 指针 + stale 传播。"""

    async def activate(
        self,
        project_id: str,
        user_id: str,
        entity_type: str,
        version_id: str,
    ) -> dict[str, Any]:
        """激活指定版本。

        Args:
            project_id:  目标项目 ID。
            user_id:     当前用户 ID（项目归属校验）。
            entity_type: 版本类型（brief / style / storyboard / timeline）。
            version_id:  要激活的版本 ID。

        Returns:
            包含切换结果摘要的 dict。

        Raises:
            VersionSwitchError: 参数非法、版本不存在或不属于项目。
        """
        if entity_type not in SUPPORTED_ENTITY_TYPES:
            raise VersionSwitchError(
                f"不支持的实体类型: {entity_type!r}，"
                f"支持: {sorted(SUPPORTED_ENTITY_TYPES)}",
                code="unsupported_entity_type",
            )

        dispatch = {
            "brief": self._activate_brief,
            "style": self._activate_style,
            "storyboard": self._activate_storyboard,
            "timeline": self._activate_timeline,
        }
        return await dispatch[entity_type](project_id, user_id, version_id)

    # ------------------------------------------------------------------
    # brief 版本切换
    # ------------------------------------------------------------------

    async def _activate_brief(
        self, project_id: str, user_id: str, version_id: str
    ) -> dict[str, Any]:
        """切换 creative_brief 版本。

        传播范围（doc 04 §12.2）：shot_plan / storyboard / clips / timeline 全部失效。
        项目退到 audio_analyzed。
        """
        async with UnitOfWork() as uow:
            session = uow.session

            project = await self._require_project(session, project_id, user_id)
            repo = CreativeBriefRepository(session)

            target = await repo.get_by_id_for_project(version_id, project_id)
            if target is None:
                raise VersionSwitchError(
                    "目标 brief 版本不存在或不属于该项目", code="version_not_found"
                )

            # 切换 active 指针
            await repo.deactivate_all(project_id)
            target.is_active = True
            session.add(target)
            project.active_brief_version_id = version_id
            session.add(project)

            # stale 传播（BRIEF_CHANGED → 项目退到 audio_analyzed）
            await state_transition_service.mark_stale(
                session, project, StaleScope.BRIEF_CHANGED
            )
            # 事件日志
            await event_log_service.emit(
                session,
                ProjectEvent(
                    project_id=project_id,
                    aggregate_type="brief",
                    aggregate_id=version_id,
                    event_type="brief_version_activated",
                    category="domain",
                    payload={"version_id": version_id, "version_no": target.version_no},
                ),
            )
            # 重建决策（doc 04 §14.2）
            await self._create_rebuild_decision(
                session,
                project_id=project_id,
                decision_type="rebuild_after_brief_switch",
                description="自动重新生成 Shot Plan（及后续 Storyboard / Clips / Timeline）",
                target_entity_type="brief",
                target_entity_id=version_id,
            )

        _logger.info(
            f"Brief 版本切换完成: project={project_id!r} → v={target.version_no}",
            event_type="brief_version_switched",
        )
        return {
            "entity_type": "brief",
            "activated_version_id": version_id,
            "version_no": target.version_no,
            "stale_propagation": "shot_plan / storyboard / clips / timeline",
            "project_stage_after": ProjectStage.AUDIO_ANALYZED.value,
        }

    # ------------------------------------------------------------------
    # style 版本切换
    # ------------------------------------------------------------------

    async def _activate_style(
        self, project_id: str, user_id: str, version_id: str
    ) -> dict[str, Any]:
        """切换 style_bible 版本。

        传播范围（doc 04 §12.2）：storyboard / prompt_bundles / clips / timeline 失效。
        项目退到 shot_plan_ready。
        """
        async with UnitOfWork() as uow:
            session = uow.session

            project = await self._require_project(session, project_id, user_id)
            repo = StyleBibleRepository(session)

            target = await repo.get_by_id_for_project(version_id, project_id)
            if target is None:
                raise VersionSwitchError(
                    "目标 style 版本不存在或不属于该项目", code="version_not_found"
                )

            await repo.deactivate_all(project_id)
            target.is_active = True
            session.add(target)
            project.active_style_version_id = version_id
            session.add(project)

            # stale 传播（STYLE_CHANGED → 项目退到 shot_plan_ready）
            await state_transition_service.mark_stale(
                session, project, StaleScope.STYLE_CHANGED
            )
            # 事件日志
            await event_log_service.emit(
                session,
                ProjectEvent(
                    project_id=project_id,
                    aggregate_type="style",
                    aggregate_id=version_id,
                    event_type="style_version_activated",
                    category="domain",
                    payload={"version_id": version_id, "version_no": target.version_no},
                ),
            )

        _logger.info(
            f"Style 版本切换完成: project={project_id!r} → v={target.version_no}",
            event_type="style_version_switched",
        )
        return {
            "entity_type": "style",
            "activated_version_id": version_id,
            "version_no": target.version_no,
            "stale_propagation": "storyboard / clips / timeline",
            "project_stage_after": ProjectStage.SHOT_PLAN_READY.value,
        }

    # ------------------------------------------------------------------
    # storyboard 版本切换
    # ------------------------------------------------------------------

    async def _activate_storyboard(
        self, project_id: str, user_id: str, version_id: str
    ) -> dict[str, Any]:
        """切换 storyboard 版本。

        传播范围（doc 04 §12.2）：clips / timeline 失效。
        项目退到 storyboard_ready（不能错误退到 brief 或 audio 阶段）。
        """
        async with UnitOfWork() as uow:
            session = uow.session

            project = await self._require_project(session, project_id, user_id)
            repo = StoryboardVersionRepository(session)

            target = await repo.get_by_id_for_project(version_id, project_id)
            if target is None:
                raise VersionSwitchError(
                    "目标 storyboard 版本不存在或不属于该项目", code="version_not_found"
                )

            await repo.deactivate_all(project_id)
            target.is_active = True
            session.add(target)
            project.active_storyboard_version_id = version_id
            session.add(project)

            # storyboard 切换：只让 clips 和 timeline 失效
            await self._mark_clips_stale(session, project_id)
            await self._mark_timeline_stale(session, project_id)

            # 项目退到 storyboard_ready（只在当前阶段比 storyboard_ready 更靠后时才退）
            if project.current_stage in _STAGES_AFTER_STORYBOARD:
                await state_transition_service.advance_project(
                    session, project, ProjectStage.STORYBOARD_READY
                )
            # 事件日志
            await event_log_service.emit(
                session,
                ProjectEvent(
                    project_id=project_id,
                    aggregate_type="storyboard",
                    aggregate_id=version_id,
                    event_type="storyboard_version_activated",
                    category="domain",
                    payload={"version_id": version_id, "version_no": target.version_no},
                ),
            )
            # 重建决策（doc 04 §14.3）
            await self._create_rebuild_decision(
                session,
                project_id=project_id,
                decision_type="rebuild_after_storyboard_switch",
                description="自动重新生成 Clips（及 Timeline）",
                target_entity_type="storyboard",
                target_entity_id=version_id,
            )

        _logger.info(
            f"Storyboard 版本切换完成: project={project_id!r} → v={target.version_no}",
            event_type="storyboard_version_switched",
        )
        return {
            "entity_type": "storyboard",
            "activated_version_id": version_id,
            "version_no": target.version_no,
            "stale_propagation": "clips / timeline",
            "project_stage_after": ProjectStage.STORYBOARD_READY.value,
        }

    # ------------------------------------------------------------------
    # timeline 版本切换
    # ------------------------------------------------------------------

    async def _activate_timeline(
        self, project_id: str, user_id: str, version_id: str
    ) -> dict[str, Any]:
        """切换 timeline 版本。

        只变更 active 指针，不影响上游任何产物（doc 04 §14.4）。
        """
        async with UnitOfWork() as uow:
            session = uow.session

            project = await self._require_project(session, project_id, user_id)
            tv_repo = TimelineVersionRepository(session)

            # 按 ID 查目标版本，并验证项目归属
            result = await session.execute(
                select(TimelineVersion).where(
                    TimelineVersion.id == version_id,
                    TimelineVersion.project_id == project_id,
                )
            )
            target = result.scalar_one_or_none()
            if target is None:
                raise VersionSwitchError(
                    "目标 timeline 版本不存在或不属于该项目", code="version_not_found"
                )

            await tv_repo.deactivate_all(project_id)
            target.is_active = True
            session.add(target)
            project.active_timeline_version_id = version_id
            session.add(project)
            # 事件日志
            await event_log_service.emit(
                session,
                ProjectEvent(
                    project_id=project_id,
                    aggregate_type="timeline",
                    aggregate_id=version_id,
                    event_type="timeline_version_activated",
                    category="domain",
                    payload={"version_id": version_id, "version_no": target.version_no},
                ),
            )

        _logger.info(
            f"Timeline 版本切换完成: project={project_id!r} → v={target.version_no}",
            event_type="timeline_version_switched",
        )
        return {
            "entity_type": "timeline",
            "activated_version_id": version_id,
            "version_no": target.version_no,
            "stale_propagation": "none（不影响上游）",
            "project_stage_after": project.current_stage,
        }

    # ------------------------------------------------------------------
    # 辅助：项目归属校验
    # ------------------------------------------------------------------

    @staticmethod
    async def _require_project(
        session: AsyncSession, project_id: str, user_id: str
    ) -> Any:
        """校验项目存在且属于当前用户，否则抛 VersionSwitchError。"""
        project = await ProjectRepository(session).get_by_id_for_user(
            project_id, user_id
        )
        if project is None:
            raise VersionSwitchError("项目不存在", code="project_not_found")
        return project

    # ------------------------------------------------------------------
    # 辅助：stale 标记
    # ------------------------------------------------------------------

    @staticmethod
    async def _mark_clips_stale(
        session: AsyncSession, project_id: str
    ) -> None:
        """将项目所有 active clip_versions 标记为 stale，并将已有 clip 的 shots 一并标记 stale。

        用于 storyboard 切换场景：新 storyboard 的画面不同，基于旧分镇生成的 clip 与
        当前 storyboard 不一致，必须标记失效。
        shots.status 同步更新以符合 doc05 §21.5 失效状态落库规则。
        """
        clip_stmt = text(
            "UPDATE clip_versions SET status = 'stale' "
            "WHERE project_id = :project_id AND is_active = TRUE"
        )
        await session.execute(clip_stmt, {"project_id": project_id})
        # 同步标记已有 clip 的 shot（不标记 planned/failed 状态的 shot）
        shot_stmt = text(
            "UPDATE shots SET status = 'stale', updated_at = NOW() "
            "WHERE project_id = :project_id "
            "AND status NOT IN ('planned', 'storyboard_ready', 'failed')"
        )
        await session.execute(shot_stmt, {"project_id": project_id})

    @staticmethod
    async def _mark_timeline_stale(
        session: AsyncSession, project_id: str
    ) -> None:
        """将项目 active timeline 的 render_status 标记为 stale。"""
        stmt = text(
            "UPDATE timeline_versions SET render_status = 'stale' "
            "WHERE project_id = :project_id AND is_active = TRUE"
        )
        await session.execute(stmt, {"project_id": project_id})

    @staticmethod
    async def _create_rebuild_decision(
        session: AsyncSession,
        project_id: str,
        decision_type: str,
        description: str,
        target_entity_type: str,
        target_entity_id: str | None = None,
    ) -> None:
        """为版本切换后的重建操作创建挂起决策（doc 04 §14.2 / §14.3）。

        若无 active 会话则跳过。已有同类型 open 决策时幂等跳过。

        Args:
            session:             调用方 AsyncSession（内部的 UoW 事务中）。
            project_id:          项目 ID。
            decision_type:       决策类型，如 "rebuild_after_brief_switch"。
            description:         "yes" 选项的文字说明。
            target_entity_type:  影响的实体类型。
            target_entity_id:    影响的实体 ID（可空）。
        """
        conv_sess = await ConversationSessionRepository(session).get_active_for_project(
            project_id
        )
        if conv_sess is None:
            _logger.info(
                f"项目 {project_id!r} 无 active 会话，跳过创建版本切换决策",
                event_type="version_switch_no_session",
            )
            return
        # 幂等检查：同类型已有 open 决策则跳过
        existing = await DecisionRepository(session).list_by_type(
            project_id, decision_type, status="open"
        )
        if existing:
            return
        decision = PendingDecision(
            project_id=project_id,
            session_id=conv_sess.id,
            decision_type=decision_type,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
            status="open",
            options_payload=[
                {"id": "yes", "label": description},
                {"id": "no", "label": "暂不重建，稍后手动操作"},
            ],
            default_option_id="yes",
        )
        session.add(decision)
        _logger.info(
            f"版本切换决策创建: type={decision_type!r} project={project_id!r}",
            event_type="version_switch_decision_created",
        )
