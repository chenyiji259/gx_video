"""导出服务（Export Service）。

来源文档：doc 09 任务 11-08

职责：
  1. 读取当前激活的 TimelineVersion
  2. 调用 ffmpeg 生成指定分辨率的导出视频（720p / 1080p / 2K / 4K）
  3. 上传到 MinIO → 落 Asset
  4. 创建 ExportVersion 记录（completed）
  5. 推进项目状态 → export_ready
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from app.core.logging import get_project_logger
from app.domain.states import ProjectStage
from app.models.asset import Asset
from app.models.export import ExportVersion
from app.repositories.asset_repository import AssetRepository
from app.repositories.export_repository import ExportRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.timeline_repository import TimelineVersionRepository
from app.repositories.unit_of_work import UnitOfWork
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

ExportResolution = Literal["720p", "1080p", "2K", "4K"]

# 分辨率对应 ffmpeg scale 参数
_RESOLUTION_MAP: dict[str, str] = {
    "720p": "1280:720",
    "1080p": "1920:1080",
    "2K": "2560:1440",
    "4K": "3840:2160",
}


class ExportError(Exception):
    """导出业务异常。"""

    def __init__(self, message: str, code: str = "export_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ExportService:
    """导出服务：timeline_ready → export_ready。"""

    def __init__(self) -> None:
        self._ffmpeg = FFmpegTimelineTool()

    async def export_and_save(
        self,
        project_id: str,
        user_id: str,
        resolution: ExportResolution = "720p",
    ) -> ExportVersion:
        """执行完整导出流程。

        Args:
            project_id:  目标项目 ID。
            user_id:     当前用户 ID。
            resolution:  导出分辨率（720p / 1080p / 2K / 4K）。

        Returns:
            新建的 ExportVersion 记录（status=completed）。

        Raises:
            ExportError: 前置条件不满足、合成失败。
            FFmpegNotAvailableError: ffmpeg 不可用。
        """
        logger = get_project_logger(project_id, module="services.export")

        # ---- 步骤 1: 校验上下文 ----------------------------------------
        async with UnitOfWork() as uow:
            session = uow.session

            project = await ProjectRepository(session).get_by_id_for_user(
                project_id, user_id
            )
            if project is None:
                raise ExportError("项目不存在", code="project_not_found")

            allowed = {
                ProjectStage.TIMELINE_READY.value,
                ProjectStage.EXPORT_READY.value,
            }
            if project.current_stage not in allowed:
                raise ExportError(
                    f"当前阶段 {project.current_stage!r} 不允许导出",
                    code="invalid_stage",
                )

            tl_version = await TimelineVersionRepository(session).get_active(project_id)
            if tl_version is None:
                raise ExportError(
                    "未找到激活的 timeline，请先完成时间线合成",
                    code="no_timeline",
                )

            # 读取 preview asset（用作 export 输入）
            payload = tl_version.raw_payload or {}
            preview_asset_id = payload.get("preview_asset_id")
            if not preview_asset_id:
                raise ExportError(
                    "timeline 中无 preview asset，请重新合成时间线",
                    code="no_preview_asset",
                )
            preview_asset = await AssetRepository(session).get_by_id(preview_asset_id)
            if preview_asset is None:
                raise ExportError(
                    "timeline preview asset 不存在", code="preview_asset_missing"
                )

        # ---- 步骤 2: 准备本地 preview 文件 ----------------------------------------
        store = LocalArtifactStore(project_id)
        timeline_dir = store.planner.project_dir / "09_timeline"
        export_dir = store.planner.project_dir / "10_export"
        export_dir.mkdir(parents=True, exist_ok=True)

        preview_path = await self._get_preview_path(
            preview_asset, timeline_dir, logger
        )
        output_filename = f"export_{resolution}.mp4"
        output_path = export_dir / output_filename

        # ---- 步骤 3: ffmpeg 转码到目标分辨率 ----------------------------------------
        scale = _RESOLUTION_MAP.get(resolution, "1280:720")
        try:
            await self._ffmpeg.transcode_to_resolution(preview_path, output_path, scale)
        except TimelineCompositionError as exc:
            raise ExportError(f"ffmpeg 转码失败：{exc.message}", code=exc.code) from exc

        # ---- 步骤 4: 上传到 MinIO（流式上传，避免将大文件读入内存） --------
        export_asset_id = generate_ulid()
        object_key = (
            f"projects/{project_id}/assets/export/{export_asset_id}/{output_filename}"
        )
        storage = get_storage()
        await storage.async_upload_file(object_key, output_path, content_type="video/mp4")
        storage_uri = storage.get_permanent_url(object_key)
        export_size_bytes = output_path.stat().st_size

        # ---- 步骤 5: 落库 + 推进状态 ----------------------------------------
        export_version = await self._persist(
            project_id=project_id,
            tl_version_id=tl_version.id,
            export_asset_id=export_asset_id,
            object_key=object_key,
            storage_uri=storage_uri,
            export_size_bytes=export_size_bytes,
            resolution=resolution,
            logger=logger,
        )

        # 写本地快照
        store.write_json(
            ArtifactStage.EXPORT,
            f"export_{resolution}",
            {
                "export_version_id": export_version.id,
                "resolution": resolution,
                "asset_id": export_asset_id,
                "size_bytes": export_size_bytes,
            },
        )

        logger.info(
            f"导出完成: version_id={export_version.id!r} resolution={resolution}",
            event_type="export_done",
        )
        return export_version

    # ------------------------------------------------------------------
    # 落库
    # ------------------------------------------------------------------

    async def _persist(
        self,
        *,
        project_id: str,
        tl_version_id: str,
        export_asset_id: str,
        object_key: str,
        storage_uri: str,
        export_size_bytes: int,
        resolution: str,
        logger: Any,
    ) -> ExportVersion:
        """落库 ExportVersion + Asset + 推进项目状态。"""
        storage = get_storage()

        async with UnitOfWork() as uow:
            session = uow.session

            # 落 export asset
            export_asset = Asset(
                id=export_asset_id,
                project_id=project_id,
                asset_type="export_video",
                bucket_name=storage.default_bucket,
                object_key=object_key,
                storage_uri=storage_uri,
                mime_type="video/mp4",
                size_bytes=export_size_bytes,
                metadata_={"resolution": resolution},
            )
            await AssetRepository(session).add(export_asset)

            # 创建 ExportVersion
            export_version = ExportVersion(
                id=generate_ulid(),
                project_id=project_id,
                timeline_version_id=tl_version_id,
                asset_id=export_asset_id,
                resolution=resolution,
                status="completed",
            )
            await ExportRepository(session).add(export_version)

            # 更新项目 active 指针 + 推进状态
            project = await ProjectRepository(session).get_by_id(project_id)
            if project:
                project.latest_export_version_id = export_version.id
                session.add(project)
                if project.current_stage != ProjectStage.EXPORT_READY.value:
                    await state_transition_service.advance_project(
                        session, project, ProjectStage.EXPORT_READY
                    )

            await session.flush()
            await session.refresh(export_version)

        return export_version

    # ------------------------------------------------------------------
    # 辅助：获取 preview 本地路径
    # ------------------------------------------------------------------

    async def _get_preview_path(
        self, preview_asset: Asset, timeline_dir: Path, logger: Any
    ) -> Path:
        """获取 preview 本地文件路径，不存在则从 MinIO 下载。"""
        local_candidates = list(timeline_dir.glob("preview_*.mp4"))
        if local_candidates:
            return local_candidates[0]

        storage = get_storage()
        try:
            data = await storage.async_download_bytes(preview_asset.object_key)
            timeline_dir.mkdir(parents=True, exist_ok=True)
            local_path = timeline_dir / "preview_v1.mp4"
            await asyncio.to_thread(local_path.write_bytes, data)
            return local_path
        except Exception as exc:
            raise ExportError(
                f"timeline preview 下载失败：{exc}", code="preview_download_failed"
            ) from exc

    # _transcode 已移至 FFmpegTimelineTool.transcode_to_resolution()
    # 不再内嵌 import，直接调用 self._ffmpeg.transcode_to_resolution()
