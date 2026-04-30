"""LipSync 生成工具（LipSync Tool）。

来源文档：doc 09 任务 13-04

职责：
  接收正脸参考图 URL + 音频片段 URL + 目标时长，
  调用对应 LipSyncProviderAdapter 生成口型视频，
  将结果存入 MinIO + 落 Asset 记录 + 写本地副本，返回 (asset_id, duration_ms)。

上下游：
  输入：face_image_url, audio_segment_url, duration_sec（来自 LipSyncService）
  输出：(asset_id, duration_ms)（新建 Asset，类型 clip_video）
  调用者：LipSyncService

设计约束：
  - 模式与 VideoGenerationTool.generate_for_bundle() 完全对齐
  - 凭据全从 get_config() 读取，不 hardcode
  - 不持有媒体字节超出必要时间
"""
from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from app.core.logging import get_project_logger
from app.models.asset import Asset
from app.providers.lipsync.base import LipSyncError, get_lipsync_provider
from app.repositories.asset_repository import AssetRepository
from app.repositories.unit_of_work import UnitOfWork
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.storage_factory import get_storage
from app.utils.ids import generate_ulid


class LipSyncTool:
    """LipSync 生成工具：face_image + audio → asset_id。

    内部使用 LipSyncProviderAdapter 生成口型视频，完成后：
      1. 下载视频字节
      2. 上传到 MinIO（projects/{project_id}/assets/clip_video/...）
      3. 落库 Asset 记录
      4. 写本地副本（08_clips/）
      5. 返回 (asset_id, duration_ms)
    """

    async def generate_for_shot(
        self,
        face_image_url: str,
        audio_segment_url: str,
        duration_sec: float,
        project_id: str,
        *,
        shot_index: Optional[int] = None,
        provider_name: Optional[str] = None,
        params: Optional[dict] = None,
    ) -> tuple[str, Optional[int]]:
        """为单个 shot 生成 LipSync 视频并落库。

        Args:
            face_image_url:    正脸参考图 URL（storyboard frame 或 character ref）。
            audio_segment_url: 音频片段 URL（已裁切到 shot 时间窗口）。
            duration_sec:      目标时长（秒）。
            project_id:        所属项目 ID。
            shot_index:        镜头序号（日志用，可选）。
            provider_name:     指定 provider（None 时自动选默认）。
            params:            覆盖 provider 默认参数。

        Returns:
            (asset_id, duration_ms): 新建 Asset 的 ID + 实际视频时长（ms）。
            duration_ms 为 None 表示 provider 未返回时长信息。

        Raises:
            LipSyncError: API key 缺失、生成失败、下载失败等。
        """
        logger = get_project_logger(project_id, module="tools.lipsync")

        # ---- 步骤 1: 获取 adapter ----------------------------------------
        adapter = get_lipsync_provider(provider_name)
        provider_label = provider_name or "default_lipsync"

        # ---- 步骤 2: 调用 API 生成视频 ----------------------------------------
        logger.info(
            f"LipSync 生成开始: provider={provider_label!r} "
            f"duration={duration_sec:.1f}s shot_index={shot_index}",
            event_type="lipsync_generation_start",
        )

        try:
            result = await adapter.generate(
                face_image_url,
                audio_segment_url,
                duration_sec,
                params=params,
            )
        except LipSyncError:
            raise
        except Exception as exc:
            raise LipSyncError(
                f"LipSync 生成意外失败: {exc}", code="unexpected_error"
            ) from exc

        if not result.video_url:
            raise LipSyncError(
                "LipSync API 返回空 URL", code="empty_url"
            )

        # ---- 步骤 3: 下载视频字节 ----------------------------------------
        video_bytes = await self._download_video(result.video_url, timeout=300)

        # ---- 步骤 4: 上传到 MinIO ----------------------------------------
        asset_id = generate_ulid()
        suffix = self._infer_suffix(result.video_url)
        filename = f"lipsync_{asset_id}{suffix}"
        object_key = (
            f"projects/{project_id}/assets/clip_video/{asset_id}/{filename}"
        )
        content_type = "video/mp4" if suffix == ".mp4" else "video/mp4"

        storage = get_storage()
        await storage.async_upload_bytes(
            object_key,
            video_bytes,
            content_type=content_type,
        )
        storage_uri = storage.get_permanent_url(object_key)

        # ---- 步骤 5: 落库 Asset ----------------------------------------
        duration_ms: Optional[int] = None
        if result.duration_sec is not None:
            duration_ms = int(result.duration_sec * 1000)

        async with UnitOfWork() as uow:
            asset = Asset(
                id=asset_id,
                project_id=project_id,
                asset_type="clip_video",
                bucket_name=storage.default_bucket,
                object_key=object_key,
                storage_uri=storage_uri,
                mime_type=content_type,
                size_bytes=len(video_bytes),
                metadata_={
                    "lipsync": True,
                    "provider": provider_label,
                    "shot_index": shot_index,
                    "duration_ms": duration_ms,
                    "original_url": result.video_url,
                    "face_image_url": face_image_url,
                    "audio_segment_url": audio_segment_url,
                },
            )
            await AssetRepository(uow.session).add(asset)
            await uow.flush()

        # ---- 步骤 6: 写本地副本 ----------------------------------------
        try:
            store = LocalArtifactStore(project_id)
            clips_dir = store.planner.project_dir / "08_clips"
            clips_dir.mkdir(parents=True, exist_ok=True)
            local_path = clips_dir / filename
            await asyncio.to_thread(local_path.write_bytes, video_bytes)
        except Exception as exc:
            logger.warning(
                f"LipSync 本地副本写入失败（不影响业务）: {exc}",
                event_type="lipsync_local_copy_failed",
            )

        logger.info(
            f"LipSync 生成完成: asset_id={asset_id!r} size={len(video_bytes)} bytes "
            f"duration_ms={duration_ms}",
            event_type="lipsync_generation_done",
        )
        return asset_id, duration_ms

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    async def _download_video(url: str, timeout: int = 300) -> bytes:
        """下载视频字节。"""
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.content
            except httpx.TimeoutException as exc:
                raise LipSyncError(
                    f"下载 LipSync 视频超时: {url[:100]}", code="download_timeout"
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise LipSyncError(
                    f"下载 LipSync 视频失败 {exc.response.status_code}: {url[:100]}",
                    code="download_error",
                ) from exc
            except Exception as exc:
                raise LipSyncError(
                    f"下载 LipSync 视频意外失败: {exc}", code="download_unexpected"
                ) from exc

    @staticmethod
    def _infer_suffix(url: str) -> str:
        """从 URL 推断视频文件扩展名，默认 .mp4。"""
        lower = url.lower().split("?")[0]
        for ext in (".mp4", ".mov", ".webm"):
            if lower.endswith(ext):
                return ext
        return ".mp4"
