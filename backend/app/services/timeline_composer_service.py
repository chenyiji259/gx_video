"""时间线合成服务（Timeline Composer Service）。

来源文档：doc 09 任务 11-06

职责：
  1. 读取项目所有 active ClipVersion，按 shot_index 排序
  2. 下载本地 clip 文件（本地副本 08_clips/）
  3. 调用 FFmpegTimelineTool.compose_preview() 合成 preview
  4. 上传 preview 到 MinIO → 落 Asset
  5. 创建 TimelineVersion + TimelineSegments
  6. 写本地快照（09_timeline/）
  7. 推进项目状态 → timeline_ready
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.core.logging import get_project_logger
from app.domain.states import ProjectStage
from app.models.asset import Asset
from app.models.timeline import TimelineSegment, TimelineVersion
from app.repositories.asset_repository import AssetRepository
from app.repositories.clip_repository import ClipRepository
from app.repositories.planning_repositories import ShotRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.project_spec_repository import ProjectSpecRepository
from app.repositories.timeline_repository import (
    TimelineSegmentRepository,
    TimelineVersionRepository,
)
from app.repositories.unit_of_work import UnitOfWork
from app.services.concurrency_guard_service import ConcurrencyError, concurrency_guard
from app.services.state_transition_service import state_transition_service
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.storage_factory import get_storage
from app.storage.path_planner import ArtifactStage
from app.tools.ffmpeg_timeline_tool import (
    FFmpegNotAvailableError,
    FFmpegTimelineTool,
    TimelineCompositionError,
)
from app.utils.ids import generate_ulid


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class TimelineError(Exception):
    """时间线合成业务异常。"""

    def __init__(self, message: str, code: str = "timeline_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# TimelineComposerService
# ---------------------------------------------------------------------------

class TimelineComposerService:
    """时间线合成服务：clips_ready → timeline_ready。"""

    def __init__(self) -> None:
        self._ffmpeg = FFmpegTimelineTool()

    async def compose_and_save(
        self,
        project_id: str,
        user_id: str,
    ) -> TimelineVersion:
        """执行完整时间线合成流程。

        Args:
            project_id: 目标项目 ID。
            user_id:    当前用户 ID（项目归属校验）。

        Returns:
            新建并激活的 TimelineVersion。

        Raises:
            TimelineError: 前置条件不满足、clip 不足、合成失败。
            FFmpegNotAvailableError: ffmpeg 不可用（直接向上传递，不降级）。
        """
        logger = get_project_logger(project_id, module="services.timeline")

        # BUG-03 修复：防止同一项目并发触发两次时间线合成。
        # 16-03：150s → 600s（下载 30+ clip + ffmpeg concat 预留 10 分钟）
        try:
            async with concurrency_guard.project_lock(project_id, timeout_sec=600):
                return await self._compose_locked(project_id, user_id)
        except ConcurrencyError as exc:
            raise TimelineError(str(exc), code="concurrency_conflict") from exc

    async def _compose_locked(
        self,
        project_id: str,
        user_id: str,
    ) -> "TimelineVersion":
        """加锁后的实际执行体。"""
        logger = get_project_logger(project_id, module="services.timeline")

        # ---- 步骤 1: 校验并读取上下文 ----------------------------------------
        async with UnitOfWork() as uow:
            session = uow.session

            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None:
                raise TimelineError("项目不存在", code="project_not_found")

            allowed = {
                ProjectStage.CLIPS_READY.value,
                ProjectStage.TIMELINE_READY.value,
            }
            if project.current_stage not in allowed:
                raise TimelineError(
                    f"当前阶段 {project.current_stage!r} 不允许合成时间线",
                    code="invalid_stage",
                )

            # 读取所有 active clips，按 shot_index 排序
            clip_repo = ClipRepository(session)
            clips = await clip_repo.list_active_by_project(project_id)
            if not clips:
                raise TimelineError(
                    "没有找到 active clip，请先完成视频片段生成",
                    code="no_clips",
                )

            # 读取 shots（获取 shot_index 和时间信息）
            shot_repo = ShotRepository(session)
            all_shots = await shot_repo.list_by_project(project_id)
            shot_map = {s.id: s for s in all_shots}

            # 读取 clip 资产（获取本地路径）
            asset_repo = AssetRepository(session)
            clip_assets: dict[str, Asset] = {}
            for clip in clips:
                asset = await asset_repo.get_by_id(clip.asset_id)
                if asset:
                    clip_assets[clip.id] = asset

            # 新视频流程允许没有外部音频：
            # 若 ProjectSpec 中存在 audio_asset，则作为外部配乐叠加；
            # 否则直接拼接 clip，并保留 clip 自带音轨。
            spec = await ProjectSpecRepository(session).get_active(project_id)
            audio_asset = None
            audio_start_sec = 0.0
            if spec is not None and spec.audio_asset_id:
                audio_asset = await asset_repo.get_by_id(spec.audio_asset_id)
                if audio_asset is None:
                    raise TimelineError("音频 asset 不存在", code="audio_asset_missing")
                audio_start_sec = float(spec.audio_start_sec or 0)
                logger.info(
                    f"时间线合成将叠加外部音频: spec_id={spec.id!r} audio_asset_id={spec.audio_asset_id!r}",
                    event_type="timeline_audio_mode_external",
                )
            else:
                logger.info(
                    "时间线合成未检测到外部音频，改为使用 clip 自带音轨拼接",
                    event_type="timeline_audio_mode_embedded",
                )

        # 按 shot_index 排序 clips
        def _shot_index(clip: Any) -> int:
            shot = shot_map.get(clip.shot_id)
            return shot.shot_index if shot else 999

        sorted_clips = sorted(clips, key=_shot_index)

        # ---- 步骤 2: 准备本地 clip 路径 ----------------------------------------
        store = LocalArtifactStore(project_id)
        clips_dir = store.planner.project_dir / "08_clips"
        timeline_dir = store.planner.project_dir / "09_timeline"
        timeline_dir.mkdir(parents=True, exist_ok=True)

        # 下载缺少本地副本的 clip 文件
        clip_paths = await self._collect_clip_paths(
            sorted_clips, clip_assets, clips_dir, logger
        )

        if not clip_paths:
            raise TimelineError(
                "没有找到可用的 clip 本地文件，无法合成时间线",
                code="no_local_clips",
            )

        # 获取音频本地路径
        audio_path = None
        if audio_asset is not None:
            audio_path = await self._get_audio_path(
                audio_asset, store, project_id, logger
            )

        # ---- 步骤 3: ffmpeg 合成 preview ----------------------------------------
        preview_filename = "preview_v1.mp4"
        output_path = timeline_dir / preview_filename

        logger.info(
            f"开始时间线合成: {len(clip_paths)} 个 clip",
            event_type="timeline_compose_start",
        )

        try:
            await self._ffmpeg.compose_preview(
                clip_paths=clip_paths,
                audio_path=audio_path,
                output_path=output_path,
                audio_start_sec=audio_start_sec,
            )
        except FFmpegNotAvailableError:
            raise  # 直接向上传递，不降级
        except TimelineCompositionError as exc:
            raise TimelineError(
                f"ffmpeg 合成失败：{exc.message}", code=exc.code
            ) from exc

        # ---- 步骤 4: 上传 preview 到 MinIO（从文件流式上传，避免将大文件读入内存） ------
        preview_asset_id = generate_ulid()
        object_key = (
            f"projects/{project_id}/assets/timeline_preview/"
            f"{preview_asset_id}/{preview_filename}"
        )
        storage = get_storage()
        await storage.async_upload_file(
            object_key,
            output_path,
            content_type="video/mp4",
        )
        storage_uri = storage.get_permanent_url(object_key)
        preview_size_bytes = output_path.stat().st_size

        # ---- 步骤 5: 落库 Asset + TimelineVersion + Segments ----------------------------------------
        timeline_version = await self._persist(
            project_id=project_id,
            preview_asset_id=preview_asset_id,
            object_key=object_key,
            storage_uri=storage_uri,
            preview_size_bytes=preview_size_bytes,
            sorted_clips=sorted_clips,
            shot_map=shot_map,
            audio_asset=audio_asset,
            logger=logger,
        )

        # ---- 步骤 6: 写本地快照 ----------------------------------------
        store.write_json(
            ArtifactStage.TIMELINE,
            "timeline_summary",
            {
                "timeline_version_id": timeline_version.id,
                "version_no": timeline_version.version_no,
                "segment_count": len(sorted_clips),
                "preview_asset_id": preview_asset_id,
            },
        )

        logger.info(
            f"时间线合成完成: version_id={timeline_version.id!r} "
            f"segments={len(sorted_clips)}",
            event_type="timeline_compose_done",
        )
        return timeline_version

    # ------------------------------------------------------------------
    # 落库
    # ------------------------------------------------------------------

    async def _persist(
        self,
        *,
        project_id: str,
        preview_asset_id: str,
        object_key: str,
        storage_uri: str,
        preview_size_bytes: int,
        sorted_clips: list[Any],
        shot_map: dict[str, Any],
        audio_asset: Any | None,
        logger: Any,
    ) -> TimelineVersion:
        """落库 Asset + TimelineVersion + TimelineSegments + 状态推进。"""
        storage = get_storage()

        async with UnitOfWork() as uow:
            session = uow.session
            asset_repo = AssetRepository(session)
            tv_repo = TimelineVersionRepository(session)
            seg_repo = TimelineSegmentRepository(session)
            proj_repo = ProjectRepository(session)

            # 落 preview asset（timeline preview 归类为 export_video，无独立类型）
            preview_asset = Asset(
                id=preview_asset_id,
                project_id=project_id,
                asset_type="export_video",
                bucket_name=storage.default_bucket,
                object_key=object_key,
                storage_uri=storage_uri,
                mime_type="video/mp4",
                size_bytes=preview_size_bytes,
                metadata_={"preview_type": "timeline"},
            )
            await asset_repo.add(preview_asset)

            # 失活旧版本
            await tv_repo.deactivate_all(project_id)
            version_no = await tv_repo.get_next_version_no(project_id)

            # 构建 segments payload（按 shot 顺序）
            cursor_ms = 0
            segments_payload = []
            for clip in sorted_clips:
                shot = shot_map.get(clip.shot_id)
                duration_ms = clip.duration_ms or (shot.duration_ms if shot else 5000) or 5000
                shot_audio_strategy = None
                if shot is not None and isinstance(getattr(shot, "style_binding", None), list):
                    for item in shot.style_binding:
                        if isinstance(item, dict) and item.get("type") == "audio_strategy":
                            shot_audio_strategy = item.get("value")
                            break
                        if isinstance(item, dict) and isinstance(item.get("audio_strategy"), dict):
                            shot_audio_strategy = item.get("audio_strategy")
                            break
                seg_data = {
                    "shot_id": clip.shot_id,
                    "clip_version_id": clip.id,
                    "start_ms": cursor_ms,
                    "end_ms": cursor_ms + duration_ms,
                    "audio_strategy": shot_audio_strategy,
                }
                segments_payload.append(seg_data)
                cursor_ms += duration_ms

            total_duration_ms = cursor_ms

            # 创建 TimelineVersion
            tl_version = TimelineVersion(
                id=generate_ulid(),
                project_id=project_id,
                version_no=version_no,
                audio_asset_id=audio_asset.id if audio_asset is not None else None,
                subtitle_track=[],
                render_status="ready",
                raw_payload={
                    "segment_count": len(sorted_clips),
                    "total_duration_ms": total_duration_ms,
                    "preview_asset_id": preview_asset_id,
                    "audio_mode": "external" if audio_asset is not None else "embedded",
                    "segments": segments_payload,
                },
                is_active=True,
            )
            await tv_repo.add(tl_version)
            await session.flush()
            await session.refresh(tl_version)

            # 创建 TimelineSegments
            segments: list[TimelineSegment] = []
            for seg_data in segments_payload:
                seg = TimelineSegment(
                    id=generate_ulid(),
                    timeline_version_id=tl_version.id,
                    shot_id=seg_data["shot_id"],
                    clip_version_id=seg_data["clip_version_id"],
                    start_ms=seg_data["start_ms"],
                    end_ms=seg_data["end_ms"],
                    metadata_={
                        "auto_composed": True,
                        "audio_strategy": seg_data.get("audio_strategy"),
                    },
                )
                segments.append(seg)
            await seg_repo.bulk_add(segments)

            # 更新项目 active 指针
            project = await proj_repo.get_by_id(project_id)
            if project:
                project.active_timeline_version_id = tl_version.id
                session.add(project)

                if project.current_stage != ProjectStage.TIMELINE_READY.value:
                    await state_transition_service.advance_project(
                        session, project, ProjectStage.TIMELINE_READY
                    )

        return tl_version

    # ------------------------------------------------------------------
    # 辅助：收集本地 clip 文件路径
    # ------------------------------------------------------------------

    async def _collect_clip_paths(
        self,
        sorted_clips: list[Any],
        clip_assets: dict[str, Any],
        clips_dir: Path,
        logger: Any,
    ) -> list[Path]:
        """按 shot 顺序收集 clip 本地文件路径，缺失时尝试从 MinIO 下载。"""
        clip_paths: list[Path] = []
        storage = get_storage()

        for clip in sorted_clips:
            asset = clip_assets.get(clip.id)
            if asset is None:
                logger.warning(
                    f"clip {clip.id!r} 对应 asset 不存在，跳过",
                    event_type="timeline_clip_asset_missing",
                )
                continue

            # 本地副本文件命名格式为 clip_{asset_id}.{ext}（与 video_generation_tool 一致）
            local_candidates = list(clips_dir.glob(f"clip_{asset.id}*"))
            if not local_candidates:
                # 从存储下载
                try:
                    data = await storage.async_download_bytes(asset.object_key)
                    suffix = asset.object_key.rsplit(".", 1)[-1] if "." in asset.object_key else "mp4"
                    local_path = clips_dir / f"clip_{asset.id}.{suffix}"
                    clips_dir.mkdir(parents=True, exist_ok=True)
                    await asyncio.to_thread(local_path.write_bytes, data)
                    clip_paths.append(local_path)
                except Exception as exc:
                    logger.warning(
                        f"clip {clip.id!r} 下载失败，跳过: {exc}",
                        event_type="timeline_clip_download_failed",
                    )
                    continue
            else:
                clip_paths.append(local_candidates[0])

        return clip_paths

    # ------------------------------------------------------------------
    # 辅助：获取音频本地路径
    # ------------------------------------------------------------------

    async def _get_audio_path(
        self,
        audio_asset: Any,
        store: LocalArtifactStore,
        project_id: str,
        logger: Any,
    ) -> Path:
        """获取音频文件本地路径，缺失时从 MinIO 下载。"""
        input_dir = store.planner.project_dir / "01_input"
        # BUG-04 修复：AssetSyncService.sync() 写本地副本格式为 audio_original_{asset.id}.{ext}。
        # 原 glob("audio_original*") 在多次上传后会拿到 OS 排序第一个（可能是旧文件）。
        # 改为精确按 asset_id 匹配，保证拿到当前版本的音频。
        local_candidates = list(input_dir.glob(f"audio_original_{audio_asset.id}*"))

        if local_candidates:
            return local_candidates[0]

        # 从 MinIO 下载（命名与 AssetSyncService 保持一致：audio_original_{id}.{ext}）
        storage = get_storage()
        try:
            data = await storage.async_download_bytes(audio_asset.object_key)
            input_dir.mkdir(parents=True, exist_ok=True)
            suffix = audio_asset.object_key.rsplit(".", 1)[-1] if "." in audio_asset.object_key else "mp3"
            audio_path = input_dir / f"audio_original_{audio_asset.id}.{suffix}"
            await asyncio.to_thread(audio_path.write_bytes, data)
            return audio_path
        except Exception as exc:
            raise TimelineError(
                f"音频文件下载失败：{exc}", code="audio_download_failed"
            ) from exc
