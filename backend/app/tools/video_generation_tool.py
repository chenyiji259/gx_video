"""视频生成工具（Video Generation Tool）。

来源文档：doc 09 任务 11-01

职责：
  接收 PromptBundle，调用对应 VideoProviderAdapter 生成视频，
  将结果存入对象存储 + 落 Asset 记录 + 写本地副本，返回 asset_id。

上下游：
  输入：PromptBundle（来自 PromptCompilerService）
  输出：asset_id（shot_clip 类型）
  调用者：ClipService（逐 shot 调用）
"""
from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from app.core.logging import get_project_logger
from app.core.provider_registry import get_provider_registry
from app.models.asset import Asset
from app.providers.video.base import VideoGenerationError, VideoGenerationMode, get_video_provider
from app.repositories.asset_repository import AssetRepository
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.prompt import PromptBundle
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.storage_factory import get_storage
from app.utils.ids import generate_ulid


class VideoGenerationTool:
    """视频生成工具：PromptBundle → asset_id。

    内部使用 VideoProviderAdapter 生成视频，完成后：
      1. 下载视频字节
      2. 上传到对象存储（projects/{project_id}/assets/shot_clip/...）
      3. 落库 Asset 记录
      4. 写本地副本（08_clips/）
      5. 返回 asset_id
    """

    async def generate_for_bundle(
        self,
        bundle: PromptBundle,
        project_id: str,
        *,
        mode: VideoGenerationMode = "image_to_video",
        shot_index: Optional[int] = None,
        reference_image_url: Optional[str] = None,
        reference_image_urls: Optional[list[str]] = None,
        last_frame_url: Optional[str] = None,
    ) -> tuple[str, Optional[int]]:
        """为 PromptBundle 生成视频并落库。

        Args:
            bundle:               PromptBundle schema 对象。
            project_id:           所属项目 ID。
            mode:                 生成模式，默认 image_to_video。
            shot_index:           镜头序号（用于日志输出，可选）。
            reference_image_url:  旧兼容 image_to_video 模式下的起始帧 URL。
            reference_image_urls: 多图融合模式下的有序参考图 URL 列表。
            last_frame_url:       旧兼容 image_to_video 模式下的尾帧 URL。

        Returns:
            (asset_id, duration_ms): 新建 Asset 的 ID + 实际视频时长（ms）。
            duration_ms 为 None 表示 provider 未返回时长信息。

        Raises:
            VideoGenerationError: API key 缺失、生成失败、下载失败等。
        """
        logger = get_project_logger(project_id, module="tools.video_generation")

        # ---- 步骤 1: 获取 adapter ----------------------------------------
        adapter = get_video_provider(bundle.provider)

        # ---- 步骤 2: 调用 API 生成视频 ----------------------------------------
        logger.info(
            f"视频生成开始: provider={bundle.provider!r} mode={mode!r} "
            f"shot_index={shot_index} bundle_id={bundle.bundle_id!r}",
            event_type="video_generation_start",
        )

        params = dict(bundle.params or {})
        if reference_image_urls:
            params["reference_image_urls"] = list(reference_image_urls)
        if last_frame_url:
            params["last_frame_url"] = last_frame_url
        requested_duration_sec = params.get("duration_sec")
        if requested_duration_sec is not None:
            try:
                normalized_duration_sec, _ = get_provider_registry().normalize_duration(
                    "video",
                    min(float(requested_duration_sec), 15.0),
                    provider_name=bundle.provider,
                )
                params["duration_sec"] = normalized_duration_sec
            except (TypeError, ValueError):
                pass

        try:
            result = await adapter.generate(
                prompt=bundle.positive_prompt,
                mode=mode,
                negative_prompt=bundle.negative_prompt,
                reference_image_url=reference_image_url,
                params=params,
            )
        except VideoGenerationError:
            raise
        except Exception as exc:
            raise VideoGenerationError(
                f"视频生成意外失败: {exc}", code="unexpected_error"
            ) from exc

        if not result.video_url:
            raise VideoGenerationError(
                "视频生成 API 返回空 URL", code="empty_url"
            )

        # ---- 步骤 3: 下载视频字节 ----------------------------------------
        logger.info(
            f"视频下载开始: url={result.video_url[:80]}...",
            event_type="video_download_start",
        )
        video_bytes = await self._download_video(result.video_url, timeout=300)
        logger.info(
            f"视频下载完成: size={len(video_bytes)} bytes, 开始上传 MinIO",
            event_type="video_download_done",
        )

        # ---- 步骤 4: 上传到 MinIO ----------------------------------------
        asset_id = generate_ulid()
        suffix = self._infer_suffix(result.video_url)
        # 使用 asset_id 命名，保证本地副本与时间线服务查找路径一致
        filename = f"clip_{asset_id}{suffix}"
        object_key = (
            f"projects/{project_id}/assets/shot_clip/{asset_id}/{filename}"
        )
        if suffix == ".mp4":
            content_type = "video/mp4"
        elif suffix == ".mov":
            content_type = "video/quicktime"
        elif suffix == ".webm":
            content_type = "video/webm"
        else:
            content_type = "video/mp4"

        storage = get_storage()
        await storage.async_upload_bytes(
            object_key,
            video_bytes,
            content_type=content_type,
        )
        storage_uri = storage.get_permanent_url(object_key)
        logger.debug(
            f"MinIO 上传完成: object_key={object_key!r}",
            event_type="video_minio_uploaded",
        )

        # ---- 步骤 5: 落库 Asset ----------------------------------------
        duration_ms: Optional[int] = None
        if result.duration_sec is not None:
            duration_ms = int(result.duration_sec * 1000)

        # 提取外部服务任务 ID（供调试、手动恢复轮询使用）
        # ToAPIs / Kling 等 provider 在 provider_meta 中均以 "id" 字段返回任务 ID
        external_task_id: str = ""
        if result.provider_meta and isinstance(result.provider_meta, dict):
            external_task_id = str(result.provider_meta.get("id") or "")

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
                    "bundle_id": bundle.bundle_id,
                    "provider": bundle.provider,
                    "mode": mode,
                    "shot_index": shot_index,
                    "duration_ms": duration_ms,
                    "requested_duration_sec": requested_duration_sec,
                    "normalized_duration_sec": params.get("duration_sec"),
                    "original_url": result.video_url,
                    "external_task_id": external_task_id,
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
                f"视频本地副本写入失败（不影响业务）: {exc}",
                event_type="video_local_copy_failed",
            )

        logger.info(
            f"视频生成完成: asset_id={asset_id!r} size={len(video_bytes)} bytes "
            f"duration_ms={duration_ms}",
            event_type="video_generation_done",
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
                raise VideoGenerationError(
                    f"下载视频超时: {url[:100]}", code="download_timeout"
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise VideoGenerationError(
                    f"下载视频失败 {exc.response.status_code}: {url[:100]}",
                    code="download_error",
                ) from exc
            except Exception as exc:
                raise VideoGenerationError(
                    f"下载视频意外失败: {exc}", code="download_unexpected"
                ) from exc

    @staticmethod
    def _infer_suffix(url: str) -> str:
        """从 URL 推断视频后缀，默认 .mp4。"""
        url_lower = url.lower().split("?")[0]
        if url_lower.endswith(".mp4"):
            return ".mp4"
        if url_lower.endswith(".mov"):
            return ".mov"
        if url_lower.endswith(".webm"):
            return ".webm"
        return ".mp4"
