"""单镜头重编译与重生成服务（Shot Regeneration Service）。

来源文档：doc 09 任务 12-03

职责：
  对单个 stale/failed/clip_ready shot 重新编译 PromptBundle 并生成新 clip，
  更新 active ClipVersion，并同步更新 active timeline 中对应 segment 的引用。

设计约束：
  - 全程复用 G11 已有能力：PromptCompilerService / VideoGenerationTool / ClipRepository。
  - 有 active timeline 时只更新对应 segment.clip_version_id，不自动重跑 ffmpeg。
  - 接入 CostEstimationService + CreditService 做 reserve/commit/refund。
  - 不持有媒体字节（已在 VideoGenerationTool 内部处理），服务层不读取大文件。
  - 所有 DB 操作通过 UoW 管理，不同阶段的 DB 操作分开 UoW 避免长持连接。
"""
from __future__ import annotations

from typing import Any, Optional

import redis.asyncio as aioredis

from app.core.config import get_config
from app.core.logging import get_project_logger
from app.core.redis_utils import build_redis_url
from app.domain.states import ProjectStage
from app.models.clip import ClipVersion
from app.providers.video.base import VideoGenerationError
from app.schemas.event import ProjectEvent
from app.services.event_log_service import event_log_service
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
from app.services.cost_estimation_service import CostEstimationService
from app.services.concurrency_guard_service import ConcurrencyError, concurrency_guard
from app.services.asset_access_service import build_asset_access_url
from app.services.output_spec_service import TALKING_HEAD_LAYOUT
from app.services.prompt_compiler_service import PromptCompilerError, PromptCompilerService
from app.services.state_transition_service import state_transition_service
from app.services.talking_head_prompt_service import TalkingHeadPromptService
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.path_planner import ArtifactStage
from app.tools.video_generation_tool import VideoGenerationTool
from app.utils.ids import generate_ulid


# ---------------------------------------------------------------------------
# 允许触发重生成的 shot 状态
# ---------------------------------------------------------------------------

_REGENERATABLE_STATUSES: frozenset[str] = frozenset({
    "stale", "clip_ready", "failed", "storyboard_ready",
})

# 幂等键 Redis 前缀
_REGEN_IDEM_PREFIX = "vidmuse:regen:idem:"


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class ShotRegenerationError(Exception):
    """单镜头重生成业务异常。"""

    def __init__(self, message: str, code: str = "shot_regen_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# ShotRegenerationService
# ---------------------------------------------------------------------------

class ShotRegenerationService:
    """单镜头重编译与重生成服务。"""

    def __init__(self) -> None:
        self._compiler = PromptCompilerService()
        self._talking_head_compiler = TalkingHeadPromptService()
        self._video_tool = VideoGenerationTool()
        self._cost_svc = CostEstimationService()
        self._idem_redis: aioredis.Redis | None = None

    async def _get_idem_redis(self) -> aioredis.Redis:
        """Redis 客户端懒加载单例（用于幂等锁）。"""
        if self._idem_redis is None:
            self._idem_redis = aioredis.from_url(
                build_redis_url(), encoding="utf-8", decode_responses=True
            )
        return self._idem_redis

    async def _guard_idempotency_key(self, key: str) -> None:
        """\u5e42\u7b49\u952e\u9632\u91cd\u5b88\u536b\uff08Redis SET NX EX 60\uff09\u3002

        \u9996\u6b21\u8bf7\u6c42\uff1a\u5199\u5165\u6210\u529f\uff0c\u7ee7\u7eed\u751f\u6210\u3002
        60 \u79d2\u5185\u91cd\u590d\u8bf7\u6c42\uff1a key \u5df2\u5b58\u5728\uff0c\u629b idempotency_conflict\u3002
        \u751f\u6210\u6210\u529f\u540e\u8c03\u7528 _extend_idempotency_ttl \u5c06 TTL \u5ef6\u957f\u5230 300 \u79d2\u3002
        \u751f\u6210\u5931\u8d25\u540c\u5219\u5220\u9664 key \u5141\u8bb8\u5ba2\u6237\u7aef\u91cd\u8bd5\u3002
        """
        redis_client = await self._get_idem_redis()
        redis_key = f"{_REGEN_IDEM_PREFIX}{key}"
        acquired = await redis_client.set(redis_key, "1", ex=60, nx=True)
        if not acquired:
            raise ShotRegenerationError(
                f"\u5e42\u7b49\u952e {key!r} \u5bf9\u5e94\u7684\u8bf7\u6c42\u6b63\u5728\u5904\u7406\u4e2d\u6216 60 \u79d2\u5185\u5df2\u5b8c\u6210\uff0c"
                "\u8bf7\u4f7f\u7528\u65b0\u7684\u5e42\u7b49\u952e\u91cd\u8bd5",
                code="idempotency_conflict",
            )

    async def _extend_idempotency_ttl(self, key: str) -> None:
        """\u751f\u6210\u6210\u529f\u540e\u5ef6\u957f\u5e42\u7b49\u952e TTL \u81f3 300 \u79d2\uff08\u9632 5 \u5206\u949f\u5185\u91cd\u590d\u89e6\u53d1\uff09\u3002"""
        redis_client = await self._get_idem_redis()
        await redis_client.expire(f"{_REGEN_IDEM_PREFIX}{key}", 300)

    async def _release_idempotency_key(self, key: str) -> None:
        """\u751f\u6210\u5931\u8d25\u540e\u91ca\u653e\u5e42\u7b49\u952e\uff0c\u5141\u8bb8\u5ba2\u6237\u7aef\u91cd\u8bd5\u3002"""
        redis_client = await self._get_idem_redis()
        await redis_client.delete(f"{_REGEN_IDEM_PREFIX}{key}")

    async def regenerate(
        self,
        project_id: str,
        shot_id: str,
        user_id: str,
        *,
        idempotency_key: Optional[str] = None,
    ) -> ClipVersion:
        """为单个 shot 重编译 PromptBundle 并生成新 clip。

        Args:
            project_id: 目标项目 ID。
            shot_id:    目标 shot ID。
            user_id:    当前用户 ID（项目归属校验）。

        Returns:
            新建并激活的 ClipVersion。

        Raises:
            ShotRegenerationError: 前置条件不满足。
            VideoGenerationError:  视频生成失败。
        """
        logger = get_project_logger(project_id, module="services.shot_regen")

        # ---- 幂等键守卫（在一切操作前先检查，快速失败） -----------------------
        idem_locked = False
        if idempotency_key:
            await self._guard_idempotency_key(idempotency_key)
            idem_locked = True

        # ---- 步骤 1: 读取并校验上下文 ----------------------------------------
        shot, regen_context = await self._load_and_validate(
            project_id, shot_id, user_id
        )
        reference_image_urls = regen_context["reference_image_urls"]
        reference_audio_urls = regen_context["reference_audio_urls"]
        storyboard_layout = regen_context["storyboard_layout"]
        story_board_url = regen_context["story_board_url"]
        layout_reading_map = regen_context["layout_reading_map"]
        mode = "multi_image_fusion" if len(reference_image_urls) >= 3 else ("image_to_video" if reference_image_urls else "text_to_video")
        logger.info(
            f"单镜头重生成开始: shot_id={shot_id!r} mode={mode!r} "
            f"（已移除 credits 校验）",
            event_type="shot_regen_start",
        )

        # ---- 并发锁（与批量 clip 生成共享 project_lock） ----------------------------------------
        _lock_timeout = 600  # 单 shot 最多 10 分钟
        try:
            async with concurrency_guard.project_lock(project_id, timeout_sec=_lock_timeout):
                return await self._regenerate_locked(
                    project_id=project_id,
                    shot_id=shot_id,
                    shot=shot,
                    user_id=user_id,
                    mode=mode,
                    reference_image_urls=reference_image_urls,
                    reference_audio_urls=reference_audio_urls,
                    storyboard_layout=storyboard_layout,
                    story_board_url=story_board_url,
                    layout_reading_map=layout_reading_map,
                    idem_locked=idem_locked,
                    idempotency_key=idempotency_key,
                    logger=logger,
                )
        except ConcurrencyError as exc:
            if idem_locked:
                await self._release_idempotency_key(idempotency_key)  # type: ignore[arg-type]
            raise ShotRegenerationError(str(exc), code="concurrency_conflict") from exc

    async def _regenerate_locked(
        self,
        *,
        project_id: str,
        shot_id: str,
        shot: Any,
        user_id: str,
        mode: str,
        reference_image_urls: list[str],
        reference_audio_urls: list[str],
        storyboard_layout: str,
        story_board_url: str,
        layout_reading_map: dict[str, Any],
        idem_locked: bool,
        idempotency_key: str | None,
        logger: Any,
    ) -> ClipVersion:
        """加锁后的实际执行体。"""

        # ---- 步骤 2: 编译 PromptBundle ----------------------------------------
        try:
            async with UnitOfWork() as uow:
                if storyboard_layout == TALKING_HEAD_LAYOUT:
                    cfg = get_config().talking_head
                    bundle = await self._talking_head_compiler.compile_talking_head_video(
                        session=uow.session,
                        project_id=project_id,
                        shot=shot,
                        story_board_url=story_board_url,
                        layout_reading_map=layout_reading_map,
                        host_reference_assets=cfg.host_reference_image_assets,
                        reference_audio_assets=cfg.reference_audio_assets,
                    )
                else:
                    bundle = await self._compiler.compile_for_shot(
                        session=uow.session,
                        shot_id=shot_id,
                        project_id=project_id,
                        target_type="shot_clip",
                        generation_mode=mode,
                        video_reference_image_urls=reference_image_urls,
                    )
        except PromptCompilerError as exc:
            if idem_locked:
                await self._release_idempotency_key(idempotency_key)  # type: ignore[arg-type]
            raise ShotRegenerationError(
                f"Prompt 编译失败: {exc.message}", code=exc.code
            ) from exc

        # ---- 步骤 3: 生成视频 ----------------------------------------
        try:
            asset_id, actual_duration_ms = await self._video_tool.generate_for_bundle(
                bundle=bundle,
                project_id=project_id,
                mode=mode,
                shot_index=shot.shot_index,
                reference_image_url=reference_image_urls[0] if reference_image_urls else None,
                reference_image_urls=reference_image_urls,
                reference_audio_urls=reference_audio_urls,
            )
        except VideoGenerationError:
            if idem_locked:
                await self._release_idempotency_key(idempotency_key)  # type: ignore[arg-type]
            raise

        # ---- 步骤 4–5: 落库 + 更新 timeline（失败时退款） ----------------------------------------
        duration_ms = actual_duration_ms or shot.duration_ms or 5000
        try:
            clip = await self._save_clip_version(
                project_id=project_id,
                shot_id=shot_id,
                asset_id=asset_id,
                duration_ms=duration_ms,
                provider=bundle.provider,
                mode=mode,
                bundle_id=bundle.bundle_id,
            )
            await self._update_timeline_segment(
                project_id=project_id,
                shot_id=shot_id,
                new_clip_id=clip.id,
                user_id=user_id,
                logger=logger,
            )
            await self._restore_failed_project_if_ready(
                project_id=project_id,
                user_id=user_id,
                logger=logger,
            )
        except Exception:
            if idem_locked:
                await self._release_idempotency_key(idempotency_key)  # type: ignore[arg-type]
            raise

        # ---- 幂等键 TTL 延长（成功后：60s 延至 300s） ----------------------------------------
        if idem_locked:
            await self._extend_idempotency_ttl(idempotency_key)  # type: ignore[arg-type]

        # ---- 事件日志 ----------------------------------------
        async with UnitOfWork() as _ev_uow:
            await event_log_service.emit(
                _ev_uow.session,
                ProjectEvent(
                    project_id=project_id,
                    aggregate_type="shot",
                    aggregate_id=shot_id,
                    event_type="clip_regenerated",
                    category="domain",
                    payload={
                        "shot_id": shot_id,
                        "new_clip_id": clip.id,
                        "asset_id": asset_id,
                        "duration_ms": duration_ms,
                    },
                ),
            )

        # ---- 本地快照 ----------------------------------------
        store = LocalArtifactStore(project_id)
        store.write_json(
            ArtifactStage.CLIPS,
            f"regen_shot_{shot_id[:8]}",
            {
                "shot_id": shot_id,
                "shot_index": shot.shot_index,
                "new_clip_version_id": clip.id,
                "asset_id": asset_id,
                "duration_ms": duration_ms,
            },
        )

        logger.info(
            f"单镜头重生成完成: shot_id={shot_id!r} clip_id={clip.id!r}",
            event_type="shot_regen_done",
        )
        return clip

    async def _restore_failed_project_if_ready(
        self,
        *,
        project_id: str,
        user_id: str,
        logger: Any,
    ) -> None:
        """失败镜头重生成后，若所有 shot 都已有 active clip，则恢复项目阶段。"""
        async with UnitOfWork() as uow:
            session = uow.session
            project = await ProjectRepository(session).get_by_id_for_user(project_id, user_id)
            if project is None or project.current_stage != ProjectStage.FAILED.value:
                return

            shots = await ShotRepository(session).list_by_project(project_id)
            active_clips = await ClipRepository(session).list_active_by_project(project_id)
            active_shot_ids = {clip.shot_id for clip in active_clips}
            if shots and all(shot.id in active_shot_ids for shot in shots):
                await state_transition_service.advance_project(
                    session,
                    project,
                    ProjectStage.CLIPS_READY,
                )
                logger.info(
                    "失败项目已恢复到 clips_ready：所有镜头均已有 active clip",
                    event_type="shot_regen_project_restored",
                )

    # ------------------------------------------------------------------
    # 辅助：校验并加载上下文
    # ------------------------------------------------------------------

    async def _load_and_validate(
        self,
        project_id: str,
        shot_id: str,
        user_id: str,
    ) -> tuple[Any, dict[str, Any]]:
        """校验项目/shot 归属，加载 storyboard frame URL 列表。

        Returns:
            (shot ORM 对象, 重生成上下文)
        """
        async with UnitOfWork() as uow:
            session = uow.session

            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None:
                raise ShotRegenerationError("项目不存在", code="project_not_found")

            shot = await ShotRepository(session).get_by_id_for_project(
                shot_id, project_id
            )
            if shot is None:
                raise ShotRegenerationError("镜头不存在", code="shot_not_found")

            if shot.status not in _REGENERATABLE_STATUSES:
                raise ShotRegenerationError(
                    f"当前 shot 状态 {shot.status!r} 不允许重生成，"
                    f"允许状态：{sorted(_REGENERATABLE_STATUSES)}",
                    code="invalid_shot_status",
                )

            # 查找 active storyboard frame（作为 image_to_video 参考帧）
            reference_image_urls: list[str] = []
            reference_audio_urls: list[str] = []
            storyboard_layout = ""
            story_board_url = ""
            layout_reading_map: dict[str, Any] = {}
            sb_version = await StoryboardVersionRepository(session).get_active(project_id)
            if sb_version:
                raw = sb_version.raw_payload or {}
                storyboard_layout = str(raw.get("board_type") or "")
                if storyboard_layout == TALKING_HEAD_LAYOUT:
                    cfg = get_config().talking_head
                    reference_image_urls = list(cfg.host_reference_image_assets)
                    reference_audio_urls = list(cfg.reference_audio_assets)
                    parent_asset_id = raw.get("parent_asset_id")
                    if parent_asset_id:
                        parent_asset = await AssetRepository(session).get_by_id(parent_asset_id)
                        story_board_url = await build_asset_access_url(parent_asset) or ""
                    if not story_board_url:
                        story_board_url = str(raw.get("parent_asset_url") or "")
                    if not story_board_url:
                        raise ShotRegenerationError(
                            "口播故事大图缺少可访问 URL，无法重生成当前镜头",
                            code="missing_story_overview_board_url",
                        )
                    reference_image_urls.append(story_board_url)
                    layout_reading_map = dict(raw.get("layout_reading_map") or {})
                else:
                    frames = await StoryboardFrameRepository(session).list_by_shot(
                        sb_version.id, shot_id
                    )
                    for frame in frames:
                        asset = await AssetRepository(session).get_by_id(frame.asset_id)
                        asset_url = await build_asset_access_url(asset)
                        if asset_url:
                            reference_image_urls.append(asset_url)

        return shot, {
            "reference_image_urls": reference_image_urls,
            "reference_audio_urls": reference_audio_urls,
            "storyboard_layout": storyboard_layout,
            "story_board_url": story_board_url,
            "layout_reading_map": layout_reading_map,
        }

    # ------------------------------------------------------------------
    # 辅助：落库 ClipVersion
    # ------------------------------------------------------------------

    async def _save_clip_version(
        self,
        project_id: str,
        shot_id: str,
        asset_id: str,
        duration_ms: int,
        provider: str,
        mode: str,
        bundle_id: str,
    ) -> ClipVersion:
        """失活旧版本，创建并激活新 ClipVersion，更新 shot 状态。"""
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
                provider=provider,
                generation_mode=mode,
                asset_id=asset_id,
                duration_ms=duration_ms,
                prompt_bundle_id=bundle_id if len(bundle_id) <= 26 else None,
                status="ready",
                is_active=True,
            )
            await clip_repo.add(clip)

            # 更新 shot 状态
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
        """若 active timeline 存在，更新该 shot 对应 segment 的 clip_version_id。

        同时将 TimelineVersion.render_status 标记为 'stale'，
        提示用户 timeline 视频需要重新合成。不自动触发 ffmpeg。
        """
        async with UnitOfWork() as uow:
            session = uow.session

            # 读取 active timeline
            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None or not project.active_timeline_version_id:
                return  # 无 timeline，跳过

            tl_version = await TimelineVersionRepository(session).get_active(project_id)
            if tl_version is None:
                return

            # 更新对应 segment
            seg_repo = TimelineSegmentRepository(session)
            segment = await seg_repo.get_by_shot(tl_version.id, shot_id)
            if segment is None:
                logger.warning(
                    f"未找到 timeline segment: timeline={tl_version.id!r} shot={shot_id!r}",
                    event_type="timeline_segment_not_found",
                )
                return

            segment.clip_version_id = new_clip_id
            session.add(segment)

            # 标记 timeline render_status 为 stale（需要重新合成）
            tl_version.render_status = "stale"
            session.add(tl_version)

        logger.info(
            f"Timeline segment 已更新: timeline={tl_version.id!r} "
            f"shot={shot_id!r} → clip={new_clip_id!r} (render_status=stale)",
            event_type="timeline_segment_updated",
        )
