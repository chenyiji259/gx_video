"""Shot Patch 服务（Shot Patch Service）。

来源文档：doc 09 任务 12-02

职责：
  对单个 shot 的语义描述字段做结构化修改（patch），
  触发 stale 传播标记下游 clip 失效，并回退项目阶段到 clips_ready。

设计约束：
  - 只允许修改白名单字段（见 PATCHABLE_FIELDS），禁止修改主键/状态机字段。
  - stale 传播通过 StateTransitionService.mark_stale(SINGLE_SHOT_CHANGED) 完成。
  - 不直接重生成媒体，只做语义修改 + stale 标记。
  - 所有 DB 操作在同一 UoW 内完成，保证原子性。
"""
from __future__ import annotations

from typing import Any

from app.core.logging import get_project_logger
from app.domain.states import ProjectStage, StaleScope
from app.repositories.planning_repositories import ShotRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.event import ProjectEvent
from app.services.event_log_service import event_log_service
from app.services.state_transition_service import state_transition_service

# 只有已有 clip 的阶段才需要 stale 传播到 clips_ready，更早阶段只更新 shot 字段
_STAGES_WITH_CLIPS: frozenset[str] = frozenset({
    ProjectStage.CLIPS_READY.value,
    ProjectStage.TIMELINE_READY.value,
    ProjectStage.EXPORT_READY.value,
    ProjectStage.COMPLETED.value,
})


# ---------------------------------------------------------------------------
# 白名单字段
# ---------------------------------------------------------------------------

# 允许通过 patch 修改的 shot 字段（来自 doc 05 §11.1 可编辑语义字段）
PATCHABLE_FIELDS: frozenset[str] = frozenset({
    "emotion",
    "shot_type",
    "camera_language",
    "visual_energy",
    "lyric_text",
    "lipsync_required",
    "character_binding",
    "style_binding",
})


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class ShotPatchError(Exception):
    """Shot Patch 业务异常。"""

    def __init__(self, message: str, code: str = "shot_patch_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# ShotPatchService
# ---------------------------------------------------------------------------

class ShotPatchService:
    """单镜头语义修改服务：patch shot + stale 传播。"""

    async def patch(
        self,
        project_id: str,
        shot_id: str,
        user_id: str,
        patch_data: dict[str, Any],
    ) -> Any:
        """修改单个 shot 的语义字段，并触发 stale 传播。

        Args:
            project_id:  目标项目 ID。
            shot_id:     目标 shot ID。
            user_id:     当前用户 ID（项目归属校验）。
            patch_data:  待修改字段字典（仅白名单字段生效，非法字段直接忽略并报错）。

        Returns:
            更新后的 Shot ORM 对象。

        Raises:
            ShotPatchError: 项目/shot 不存在、字段非法、当前阶段不允许修改。
        """
        logger = get_project_logger(project_id, module="services.shot_patch")

        # ---- 字段合法性检查 ------------------------------------------------
        invalid_fields = set(patch_data.keys()) - PATCHABLE_FIELDS
        if invalid_fields:
            raise ShotPatchError(
                f"不允许修改以下字段: {sorted(invalid_fields)}，"
                f"可修改字段为: {sorted(PATCHABLE_FIELDS)}",
                code="forbidden_fields",
            )

        # 过滤掉 None 值（不更新）
        updates = {k: v for k, v in patch_data.items() if v is not None}
        if not updates:
            raise ShotPatchError("patch_data 中没有有效更新字段", code="empty_patch")

        async with UnitOfWork() as uow:
            session = uow.session

            # ---- 项目归属校验 ---------------------------------------------
            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None:
                raise ShotPatchError("项目不存在", code="project_not_found")

            # ---- 读取 shot 并验证归属 ------------------------------------
            shot = await ShotRepository(session).get_by_id_for_project(
                shot_id, project_id
            )
            if shot is None:
                raise ShotPatchError("镜头不存在", code="shot_not_found")

            # ---- 应用字段更新 ---------------------------------------------
            applied: list[str] = []
            for field, value in updates.items():
                setattr(shot, field, value)
                applied.append(field)
            session.add(shot)

            # ---- stale 传播：
            # 如果已有 clip（项目阶段 >= clips_ready），需要标记 clip stale 并退回阶段
            # 如果尚无 clip（shot_plan_ready / storyboard_ready 等），
            # 只标记 shot 自身 —— 不调 mark_stale 避免非法阶段跳转
            if project.current_stage in _STAGES_WITH_CLIPS:
                await state_transition_service.mark_stale(
                    session,
                    project,
                    StaleScope.SINGLE_SHOT_CHANGED,
                    shot_id=shot_id,
                )
            else:
                # 无 clip 阶段：仅标记 stale，不做阶段回退
                await state_transition_service.mark_shot_stale_only(session, shot_id)

            # ---- 事件日志（与业务写入同事务，保证原子性）
            await event_log_service.emit(
                session,
                ProjectEvent(
                    project_id=project_id,
                    aggregate_type="shot",
                    aggregate_id=shot_id,
                    event_type="shot_patched",
                    category="domain",
                    payload={"shot_id": shot_id, "updated_fields": applied},
                ),
            )

        logger.info(
            f"Shot patch 完成: shot_id={shot_id!r} 修改字段={applied}",
            event_type="shot_patched",
        )
        return shot
