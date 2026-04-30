"""单镜头 LipSync 生成服务（LipSync Service）。

来源文档：doc 09 任务 13-04

职责：
  对单个标记了 lipsync_required=True 的 shot，
  生成口型驱动视频 clip，写入 ClipVersion(generation_mode='lipsync')，
  并同步更新 active timeline 中对应 segment 的引用。

流程：
  1. 校验项目归属 + shot 的 lipsync_required 标记
  2. 获取正脸参考图 URL（storyboard frame 优先，其次 image_reference asset）
  3. 获取音频片段 URL（audio_trimmed asset 的 storage_uri）
  4. Credits reserve
  5. 调用 LipSyncTool 生成视频 → (asset_id, duration_ms)
  6. 落库 ClipVersion(generation_mode='lipsync') + 更新 shot 状态
  7. 更新 active timeline segment
  8. Credits commit
  9. 写事件日志 + 本地快照

设计约束：
  - 复用 shot_regeneration_service 中的辅助逻辑（UoW + Credits 流程）
  - 失败时 Credits refund
  - 不持有媒体字节，字节管理在 LipSyncTool 内完成
"""
from __future__ import annotations

from typing import Any, Optional

from app.core.logging import get_project_logger
from app.models.clip import ClipVersion
from app.providers.lipsync.base import LipSyncError
from app.repositories.asset_repository import AssetRepository
from app.repositories.clip_repository import ClipRepository
from app.repositories.planning_repositories import ShotRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.storyboard_repositories import (
    StoryboardFrameRepository,
    StoryboardVersionRepository,
)
from app.repositories.timeline_repository import (
    TimelineSegmentRepository,
    TimelineVersionRepository,
)
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.event import ProjectEvent
from app.services.cost_estimation_service import CostEstimationService
from app.services.asset_access_service import build_asset_access_url
from app.services.event_log_service import event_log_service
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.path_planner import ArtifactStage
from app.tools.lipsync_tool import LipSyncTool
from app.utils.ids import generate_ulid


# ---------------------------------------------------------------------------
# 允许触发 lipsync 的 shot 状态
# ---------------------------------------------------------------------------

_LIPSYNC_ALLOWED_STATUSES: frozenset[str] = frozenset({
    "storyboard_ready", "clip_ready", "stale", "failed",
})


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class LipSyncServiceError(Exception):
    """LipSync 服务层业务异常。"""

    def __init__(self, message: str, code: str = "lipsync_service_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# LipSyncService
# ---------------------------------------------------------------------------

class LipSyncService:
    """单镜头 LipSync 生成服务。"""

    def __init__(self) -> None:
        self._lipsync_tool = LipSyncTool()
        self._cost_svc = CostEstimationService()

    async def generate_for_shot(
        self,
        project_id: str,
        shot_id: str,
        user_id: str,
    ) -> ClipVersion:
        """为指定 shot 生成 LipSync clip。

        Args:
            project_id: 目标项目 ID。
            shot_id:    目标 shot ID（必须 lipsync_required=True）。
            user_id:    当前用户 ID（项目归属校验）。

        Returns:
            新建并激活的 ClipVersion（generation_mode='lipsync'）。

        Raises:
            LipSyncServiceError: 前置条件不满足。
            LipSyncError:        LipSync 生成失败。
        """
        logger = get_project_logger(project_id, module="services.lipsync")

        # ---- 步骤 1: 校验 + 加载上下文 ----------------------------------------
        shot, face_image_url, audio_segment_url = await self._load_and_validate(
            project_id, shot_id, user_id
        )
        duration_sec = (shot.duration_ms or 5000) / 1000.0

        logger.info(
            f"LipSync 生成开始: shot_id={shot_id!r} duration={duration_sec:.1f}s "
            f"face_image={bool(face_image_url)} audio={bool(audio_segment_url)} "
            f"（已移除 credits 校验）",
            event_type="lipsync_service_start",
        )

        # ---- 步骤 4: 生成 LipSync 视频 ----------------------------------------
        try:
            asset_id, actual_duration_ms = await self._lipsync_tool.generate_for_shot(
                face_image_url=face_image_url,
                audio_segment_url=audio_segment_url,
                duration_sec=duration_sec,
                project_id=project_id,
                shot_index=shot.shot_index,
            )
        except (LipSyncError, Exception):
            raise

        # ---- 步骤 5: 落库 ClipVersion（generation_mode='lipsync'）+ 更新 shot ----
        duration_ms = actual_duration_ms or shot.duration_ms or 5000
        try:
            clip = await self._save_clip_version(
                project_id=project_id,
                shot_id=shot_id,
                asset_id=asset_id,
                duration_ms=duration_ms,
            )
            await self._update_timeline_segment(
                project_id=project_id,
                shot_id=shot_id,
                new_clip_id=clip.id,
                user_id=user_id,
                logger=logger,
            )
        except Exception:
            raise

        # ---- 步骤 7: 事件日志 + 本地快照 ----------------------------------------
        async with UnitOfWork() as ev_uow:
            await event_log_service.emit(
                ev_uow.session,
                ProjectEvent(
                    project_id=project_id,
                    aggregate_type="shot",
                    aggregate_id=shot_id,
                    event_type="lipsync_clip_generated",
                    category="domain",
                    payload={
                        "shot_id": shot_id,
                        "new_clip_id": clip.id,
                        "asset_id": asset_id,
                        "duration_ms": duration_ms,
                        "generation_mode": "lipsync",
                    },
                ),
            )

        store = LocalArtifactStore(project_id)
        store.write_json(
            ArtifactStage.CLIPS,
            f"lipsync_shot_{shot_id[:8]}",
            {
                "shot_id": shot_id,
                "shot_index": shot.shot_index,
                "new_clip_version_id": clip.id,
                "asset_id": asset_id,
                "duration_ms": duration_ms,
                "generation_mode": "lipsync",
            },
        )

        logger.info(
            f"LipSync 生成完成: shot_id={shot_id!r} clip_id={clip.id!r}",
            event_type="lipsync_service_done",
        )
        return clip

    # ------------------------------------------------------------------
    # 辅助：校验并加载上下文
    # ------------------------------------------------------------------

    async def _load_and_validate(
        self,
        project_id: str,
        shot_id: str,
        user_id: str,
    ) -> tuple[Any, str, str]:
        """校验 + 加载 face_image_url 和 audio_segment_url。

        Returns:
            (shot ORM, face_image_url, audio_segment_url)

        Raises:
            LipSyncServiceError: 校验失败时。
        """
        async with UnitOfWork() as uow:
            session = uow.session

            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None:
                raise LipSyncServiceError("项目不存在", code="project_not_found")

            shot = await ShotRepository(session).get_by_id_for_project(
                shot_id, project_id
            )
            if shot is None:
                raise LipSyncServiceError("镜头不存在", code="shot_not_found")

            if not shot.lipsync_required:
                raise LipSyncServiceError(
                    f"shot {shot_id!r} 未标记为 lipsync_required=True，"
                    "请先在 shot 详情中启用口型生成",
                    code="lipsync_not_required",
                )

            if shot.status not in _LIPSYNC_ALLOWED_STATUSES:
                raise LipSyncServiceError(
                    f"当前 shot 状态 {shot.status!r} 不允许生成 lipsync，"
                    f"允许状态：{sorted(_LIPSYNC_ALLOWED_STATUSES)}",
                    code="invalid_shot_status",
                )

            # ---- 获取正脸参考图 URL（storyboard frame 优先）------
            face_image_url = ""
            sb_version = await StoryboardVersionRepository(session).get_active(
                project_id
            )
            if sb_version:
                frame = await StoryboardFrameRepository(session).get_by_shot(
                    sb_version.id, shot_id
                )
                if frame:
                    face_asset = await AssetRepository(session).get_by_id(
                        frame.asset_id
                    )
                    face_image_url = await build_asset_access_url(face_asset) or ""

            if not face_image_url:
                raise LipSyncServiceError(
                    f"shot {shot_id!r} 没有可用的正脸参考图（storyboard frame），"
                    "请先生成 storyboard 再触发 lipsync",
                    code="no_face_image",
                )

            # ---- 获取音频片段 URL（audio_trimmed 资产）------
            # 使用项目的 active project_spec 中的 audio_asset 作为音频来源
            audio_segment_url = ""
            if project.active_project_spec_version_id:
                from app.repositories.project_spec_repository import (
                    ProjectSpecRepository,
                )
                spec = await ProjectSpecRepository(session).get_active(project_id)
                if spec and spec.audio_asset_id:
                    audio_asset = await AssetRepository(session).get_by_id(
                        spec.audio_asset_id
                    )
                    audio_segment_url = await build_asset_access_url(audio_asset) or ""

            if not audio_segment_url:
                raise LipSyncServiceError(
                    "项目未找到可用的音频资产（audio_trimmed），"
                    "请确保项目输入阶段已完成音频上传",
                    code="no_audio_asset",
                )

        return shot, face_image_url, audio_segment_url

    # ------------------------------------------------------------------
    # 辅助：落库 ClipVersion（generation_mode='lipsync'）
    # ------------------------------------------------------------------

    async def _save_clip_version(
        self,
        project_id: str,
        shot_id: str,
        asset_id: str,
        duration_ms: int,
    ) -> ClipVersion:
        """失活旧版本，创建并激活新 ClipVersion(generation_mode='lipsync')。"""
        async with UnitOfWork() as uow:
            session = uow.session
            clip_repo = ClipRepository(session)

            await clip_repo.deactivate_all(shot_id)
            version_no = await clip_repo.get_next_version_no(shot_id)

            clip = ClipVersion(
                id=generate_ulid(),
                project_id=project_id,
                shot_id=shot_id,
                version_no=version_no,
                provider="hedra_character",
                generation_mode="lipsync",
                asset_id=asset_id,
                duration_ms=duration_ms,
                status="ready",
                is_active=True,
            )
            await clip_repo.add(clip)

            shot_orm = await ShotRepository(session).get_by_id(shot_id)
            if shot_orm is not None:
                shot_orm.status = "clip_ready"
                session.add(shot_orm)

            await uow.flush()
            await session.refresh(clip)

        return clip

    # ------------------------------------------------------------------
    # 辅助：更新 active timeline segment
    # ------------------------------------------------------------------

    async def _update_timeline_segment(
        self,
        project_id: str,
        shot_id: str,
        new_clip_id: str,
        user_id: str,
        logger: Any,
    ) -> None:
        """若 active timeline 存在，更新该 shot 对应 segment 的 clip_version_id。"""
        async with UnitOfWork() as uow:
            session = uow.session

            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None or not project.active_timeline_version_id:
                return

            tl_version = await TimelineVersionRepository(session).get_active(
                project_id
            )
            if tl_version is None:
                return

            seg_repo = TimelineSegmentRepository(session)
            segment = await seg_repo.get_by_shot(tl_version.id, shot_id)
            if segment is None:
                logger.warning(
                    f"未找到 timeline segment: timeline={tl_version.id!r} "
                    f"shot={shot_id!r}",
                    event_type="lipsync_timeline_segment_not_found",
                )
                return

            segment.clip_version_id = new_clip_id
            session.add(segment)
            tl_version.render_status = "stale"
            session.add(tl_version)

        logger.info(
            f"Timeline segment 已更新（lipsync）: timeline={tl_version.id!r} "
            f"shot={shot_id!r} → clip={new_clip_id!r}",
            event_type="lipsync_timeline_updated",
        )
