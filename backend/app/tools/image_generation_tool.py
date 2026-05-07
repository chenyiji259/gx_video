"""图片生成工具（Image Generation Tool）。

来源文档：doc 09 任务 10-02 / doc11 批次2

职责：
  1. generate_for_bundle()  — 接收 PromptBundle 生成 storyboard_frame
  2. generate_reference_image() — 生成角色/场景参考图，支持 txt2img 和 img2img 两种模式

上下游：
  输入：PromptBundle 或参考图生成规格 dict
  输出：asset_id（storyboard_frame / character_reference / scene_reference / prop_reference）
  调用者：StoryboardService（分镜）/ VisualBibleService（参考图）
"""
from __future__ import annotations

import time
import json
from typing import Any, Optional

import httpx

from app.core.logging import get_project_logger
from app.models.asset import Asset
from app.providers.image.base import ImageGenerationError, get_image_provider
from app.repositories.asset_repository import AssetRepository
from app.repositories.unit_of_work import UnitOfWork
from app.schemas.prompt import PromptBundle
from app.services.asset_access_service import build_asset_access_url
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.storage_factory import get_storage
from app.storage.path_planner import ArtifactStage
from app.utils.ids import generate_ulid


# asset_type 对应的存储子路径
_ASSET_TYPE_SUBPATH: dict[str, str] = {
    "storyboard_frame":    "storyboard_frame",
    "character_reference": "character_reference",
    "scene_reference":     "scene_reference",
    "prop_reference":      "prop_reference",
    "nine_grid_image":     "nine_grid",   # 兼容旧枚举名，当前存三宫格大图
}


class ImageGenerationTool:
    """图片生成工具：PromptBundle → asset_id。

    内部使用 ImageProviderAdapter 生成图片，完成后：
      1. 下载图片字节
      2. 上传到 MinIO（projects/{project_id}/assets/storyboard_frame/...）
      3. 落库 Asset 记录
      4. 写本地副本（06_storyboard/）
      5. 返回 asset_id
    """

    async def generate_for_bundle(
        self,
        bundle: PromptBundle,
        project_id: str,
        *,
        shot_index: Optional[int] = None,
    ) -> str:
        """为 PromptBundle 生成图片并落库。

        Args:
            bundle:      PromptBundle schema 对象（含 provider / positive_prompt / params）。
            project_id:  所属项目 ID（用于存储路径和日志）。
            shot_index:  镜头序号（用于本地文件命名，可选）。

        Returns:
            新建 Asset 的 asset_id。

        Raises:
            ImageGenerationError: API key 缺失、生成失败、下载失败等。
        """
        logger = get_project_logger(project_id, module="tools.image_generation")

        # ---- 步骤 1: 获取 adapter ----------------------------------------
        adapter = get_image_provider(bundle.provider)

        # ---- 步骤 2: 调用 API 生成图片 ----------------------------------------
        # 优先级：多参考图（reference_image_urls）> 单图（reference_image_url）> txt2img
        ref_urls: list[str] = getattr(bundle, "reference_image_urls", None) or []
        ref_single: str | None = getattr(bundle, "reference_image_url", None)

        if ref_urls:
            mode_label = f"multi_ref_img2img({len(ref_urls)}张)"
        elif ref_single:
            mode_label = "img2img"
        else:
            mode_label = "txt2img"

        logger.info(
            f"图片生成开始: provider={bundle.provider!r} "
            f"shot_index={shot_index} bundle_id={bundle.bundle_id!r} "
            f"mode={mode_label}",
            event_type="image_generation_start",
        )
        try:
            if ref_urls:
                # 多参考图模式：调用层传完整业务参考图，具体上限由 provider 能力决定。
                if hasattr(adapter, "generate_multi_ref_img2img"):
                    result = await adapter.generate_multi_ref_img2img(
                        prompt=bundle.positive_prompt,
                        image_urls=ref_urls,
                        strength=getattr(bundle, "reference_weight", 0.75),
                        negative_prompt=bundle.negative_prompt,
                        params=bundle.params,
                    )
                else:
                    # provider 不支持多参考图，降级为单图
                    logger.warning(
                        f"Provider {bundle.provider!r} 不支持 generate_multi_ref_img2img，"
                        f"降级为单图 img2img",
                        event_type="multi_ref_downgrade",
                    )
                    result = await adapter.generate_img2img(
                        prompt=bundle.positive_prompt,
                        image_url=ref_urls[0],
                        strength=getattr(bundle, "reference_weight", 0.75),
                        negative_prompt=bundle.negative_prompt,
                        params=bundle.params,
                    )
            elif ref_single:
                # 单图模式（向后兼容）
                result = await adapter.generate_img2img(
                    prompt=bundle.positive_prompt,
                    image_url=ref_single,
                    strength=getattr(bundle, "reference_weight", 0.75),
                    negative_prompt=bundle.negative_prompt,
                    params=bundle.params,
                )
            else:
                # 无参考图，纯文字生图
                result = await adapter.generate(
                    prompt=bundle.positive_prompt,
                    negative_prompt=bundle.negative_prompt,
                    params=bundle.params,
                )
        except ImageGenerationError:
            raise
        except Exception as exc:
            raise ImageGenerationError(
                f"图片生成意外失败: {exc}", code="unexpected_error"
            ) from exc

        if not result.image_url:
            raise ImageGenerationError(
                "图片生成 API 返回空 URL", code="empty_url"
            )

        # ---- 步骤 3: 下载图片字节 ----------------------------------------
        logger.debug(
            f"图片下载开始: url={result.image_url[:80]}",
            event_type="image_download_start",
        )
        image_bytes = await self._download_image(result.image_url, timeout=60)
        logger.debug(
            f"图片下载完成: size={len(image_bytes)} bytes",
            event_type="image_download_done",
        )

        # ---- 步骤 4: 上传到 MinIO ----------------------------------------
        asset_id = generate_ulid()
        suffix = self._infer_suffix(result.image_url)
        filename = f"frame_{shot_index:03d}{suffix}" if shot_index is not None else f"frame{suffix}"
        object_key = (
            f"projects/{project_id}/assets/storyboard_frame/{asset_id}/{filename}"
        )
        if suffix == ".png":
            content_type = "image/png"
        elif suffix == ".webp":
            content_type = "image/webp"
        else:
            content_type = "image/jpeg"

        storage = get_storage()
        await storage.async_upload_bytes(
            object_key,
            image_bytes,
            content_type=content_type,
        )
        storage_uri = storage.get_permanent_url(object_key)
        logger.debug(
            f"图片对象存储上传完成: object_key={object_key!r}",
            event_type="image_storage_uploaded",
        )

        # ---- 步骤 5: 落库 Asset ----------------------------------------
        async with UnitOfWork() as uow:
            asset = Asset(
                id=asset_id,
                project_id=project_id,
                asset_type="storyboard_frame",
                bucket_name=storage.default_bucket,
                object_key=object_key,
                storage_uri=storage_uri,
                mime_type=content_type,
                size_bytes=len(image_bytes),
                width=result.width,
                height=result.height,
                metadata_={
                    "bundle_id": bundle.bundle_id,
                    "provider": bundle.provider,
                    "shot_index": shot_index,
                    "original_url": result.image_url,
                },
            )
            await AssetRepository(uow.session).add(asset)
            await uow.flush()

        # ---- 步骤 6: 写本地副本 ----------------------------------------
        try:
            store = LocalArtifactStore(project_id)
            storyboard_dir = store.planner.storyboard_dir()
            local_path = storyboard_dir / filename
            local_path.write_bytes(image_bytes)
        except Exception as exc:
            logger.warning(
                f"本地副本写入失败（不影响业务）: {exc}",
                event_type="image_local_copy_failed",
            )

        logger.info(
            f"图片生成完成: asset_id={asset_id!r} size={len(image_bytes)} bytes",
            event_type="image_generation_done",
        )
        return asset_id

    async def generate_for_bundle_local(
        self,
        bundle: PromptBundle,
        project_id: str,
        *,
        shot_index: Optional[int] = None,
        name_prefix: str = "local_image",
    ) -> dict[str, Any]:
        """生成内部临时图片，只写本地文件，不上传 OSS、不落库 Asset。

        用于口播 clean reference：Seedance 需要立即使用 provider 返回的临时 URL，
        本地副本用于排查和效果回看，不进入前端展示资产链路。
        """
        logger = get_project_logger(project_id, module="tools.image_generation")
        adapter = get_image_provider(bundle.provider)
        ref_urls: list[str] = getattr(bundle, "reference_image_urls", None) or []
        ref_single: str | None = getattr(bundle, "reference_image_url", None)

        try:
            if ref_urls:
                if hasattr(adapter, "generate_multi_ref_img2img"):
                    result = await adapter.generate_multi_ref_img2img(
                        prompt=bundle.positive_prompt,
                        image_urls=ref_urls,
                        strength=getattr(bundle, "reference_weight", 0.75),
                        negative_prompt=bundle.negative_prompt,
                        params=bundle.params,
                    )
                else:
                    result = await adapter.generate_img2img(
                        prompt=bundle.positive_prompt,
                        image_url=ref_urls[0],
                        strength=getattr(bundle, "reference_weight", 0.75),
                        negative_prompt=bundle.negative_prompt,
                        params=bundle.params,
                    )
            elif ref_single:
                result = await adapter.generate_img2img(
                    prompt=bundle.positive_prompt,
                    image_url=ref_single,
                    strength=getattr(bundle, "reference_weight", 0.75),
                    negative_prompt=bundle.negative_prompt,
                    params=bundle.params,
                )
            else:
                result = await adapter.generate(
                    prompt=bundle.positive_prompt,
                    negative_prompt=bundle.negative_prompt,
                    params=bundle.params,
                )
        except ImageGenerationError:
            raise
        except Exception as exc:
            raise ImageGenerationError(
                f"本地临时图片生成意外失败: {exc}", code="unexpected_error"
            ) from exc

        if not result.image_url:
            raise ImageGenerationError(
                "图片生成 API 返回空 URL", code="empty_url"
            )

        image_bytes = await self._download_image(result.image_url, timeout=60)
        suffix = self._infer_suffix(result.image_url)
        shot_part = f"shot_{shot_index + 1:03d}" if shot_index is not None else "shot"
        filename = f"{name_prefix}_{shot_part}{suffix}"
        metadata_filename = f"{name_prefix}_{shot_part}.json"

        local_dir = LocalArtifactStore(project_id).planner.stage_dir(
            ArtifactStage.STORYBOARD, create=True
        )
        local_path = local_dir / filename
        local_path.write_bytes(image_bytes)
        metadata = {
            "bundle_id": bundle.bundle_id,
            "target_type": bundle.target_type,
            "target_id": bundle.target_id,
            "provider": bundle.provider,
            "shot_index": shot_index,
            "provider_url": result.image_url,
            "local_path": str(local_path),
            "width": result.width,
            "height": result.height,
            "seed": result.seed,
            "params": bundle.params,
            "reference_image_urls": ref_urls,
            "reference_weight": getattr(bundle, "reference_weight", 0.75),
        }
        (local_dir / metadata_filename).write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(
            f"本地临时图片生成完成: provider_url={result.image_url[:80]} "
            f"local_path={str(local_path)!r}",
            event_type="local_image_generation_done",
        )
        return metadata

    # ------------------------------------------------------------------
    # 参考图生成（doc11 批次2）
    # character_reference / scene_reference / prop_reference
    # ------------------------------------------------------------------

    async def generate_reference_image(
        self,
        project_id: str,
        asset_type: str,
        positive_prompt: str,
        negative_prompt: Optional[str] = None,
        *,
        generation_mode: str = "text_to_image",
        source_image_url: Optional[str] = None,
        strength: float = 0.75,
        provider_name: Optional[str] = None,
        params: Optional[dict] = None,
        subject_id: Optional[str] = None,
        subject_name: Optional[str] = None,
        version_no: int = 1,
    ) -> str:
        """生成角色/场景/道具参考图并落库。

        Args:
            project_id:       所属项目 ID。
            asset_type:       资产类型，必须为 character_reference / scene_reference / prop_reference。
            positive_prompt:  正向提示词。
            negative_prompt:  负向提示词（可选）。
            generation_mode:  "text_to_image" 或 "image_to_image"。
            source_image_url: img2img 模式下的参考图 URL。
            strength:         img2img 参考强度。
            provider_name:    指定 provider，默认自动选择。
            params:           额外参数覆写。
            subject_id:       角色/场景 ID（写入 metadata）。
            subject_name:     角色/场景名称（写入 metadata）。
            version_no:       版本号（写入 metadata）。

        Returns:
            新建 Asset 的 asset_id。

        Raises:
            ValueError:            asset_type 非法。
            ImageGenerationError:  生成失败。
        """
        _REFERENCE_TYPES = {"character_reference", "scene_reference", "prop_reference"}
        if asset_type not in _REFERENCE_TYPES:
            raise ValueError(
                f"generate_reference_image 仅支持 {_REFERENCE_TYPES}，得到: {asset_type!r}"
            )

        logger = get_project_logger(project_id, module="tools.image_generation")
        adapter = get_image_provider(provider_name)

        logger.info(
            f"参考图生成开始: asset_type={asset_type!r} mode={generation_mode!r} "
            f"subject_id={subject_id!r}",
            event_type="reference_image_generation_start",
        )

        # 调用对应模式
        if generation_mode == "image_to_image":
            if not source_image_url:
                raise ImageGenerationError(
                    "image_to_image 模式必须提供 source_image_url",
                    code="missing_source_image",
                )
            result = await adapter.generate_img2img(
                prompt=positive_prompt,
                image_url=source_image_url,
                strength=strength,
                negative_prompt=negative_prompt,
                params=params,
            )
        else:
            result = await adapter.generate(
                prompt=positive_prompt,
                negative_prompt=negative_prompt,
                params=params,
            )

        if not result.image_url:
            raise ImageGenerationError(
                f"参考图生成 API 返回空 URL ({asset_type})", code="empty_url"
            )

        # 下载图片字节
        image_bytes = await self._download_image(result.image_url, timeout=60)
        logger.debug(
            f"参考图下载完成: size={len(image_bytes)} bytes",
            event_type="reference_image_download_done",
        )

        # 确定存储路径
        asset_id = generate_ulid()
        suffix = self._infer_suffix(result.image_url)
        subpath = _ASSET_TYPE_SUBPATH.get(asset_type, asset_type)
        slug = subject_id or "ref"
        filename = f"{slug}_v{version_no}{suffix}"
        object_key = f"projects/{project_id}/assets/{subpath}/{asset_id}/{filename}"

        if suffix == ".png":
            content_type = "image/png"
        elif suffix == ".webp":
            content_type = "image/webp"
        else:
            content_type = "image/jpeg"

        # 上传到对象存储
        storage = get_storage()
        await storage.async_upload_bytes(object_key, image_bytes, content_type=content_type)
        storage_uri = storage.get_permanent_url(object_key)
        logger.info(
            f"参考图对象存储上传完成: object_key={object_key!r} "
            f"storage_uri={storage_uri!r} "
            f"endpoint={storage.endpoint!r} bucket={storage.default_bucket!r}",
            event_type="reference_image_storage_uploaded",
        )

        # 落库 Asset
        async with UnitOfWork() as uow:
            asset = Asset(
                id=asset_id,
                project_id=project_id,
                asset_type=asset_type,
                bucket_name=storage.default_bucket,
                object_key=object_key,
                storage_uri=storage_uri,
                mime_type=content_type,
                size_bytes=len(image_bytes),
                width=result.width,
                height=result.height,
                metadata_={
                    "subject_id": subject_id,
                    "subject_name": subject_name,
                    "generation_mode": generation_mode,
                    "source_asset_url": source_image_url,
                    "provider": getattr(adapter, "_provider_name", str(provider_name)),
                    "version_no": version_no,
                    "user_confirmed": False,
                    "original_url": result.image_url,
                    "positive_prompt": positive_prompt,
                    "negative_prompt": negative_prompt or "",
                },
            )
            await AssetRepository(uow.session).add(asset)
            await uow.flush()
        logger.info(
            f"参考图 Asset 已入库: asset_id={asset_id!r} "
            f"asset_type={asset_type!r} storage_uri={storage_uri!r}",
            event_type="reference_image_asset_persisted",
        )

        # 写本地副本（失败不阻塞业务）
        try:
            store = LocalArtifactStore(project_id)
            stage_map = {
                "character_reference": ArtifactStage.STYLE,
                "scene_reference":     ArtifactStage.STYLE,
                "prop_reference":      ArtifactStage.STYLE,
            }
            stage = stage_map.get(asset_type, ArtifactStage.STYLE)
            local_dir = store.planner.stage_dir(stage, create=True)
            (local_dir / filename).write_bytes(image_bytes)
        except Exception as exc:
            logger.warning(
                f"参考图本地副本写入失败（不影响业务）: {exc}",
                event_type="reference_local_copy_failed",
            )

        logger.info(
            f"参考图生成完成: asset_id={asset_id!r} type={asset_type!r} "
            f"size={len(image_bytes)} bytes",
            event_type="reference_image_generation_done",
        )
        return asset_id

    # ------------------------------------------------------------------
    # 三宫格生图与切分
    # ------------------------------------------------------------------

    async def generate_nine_grid(
        self,
        bundle: PromptBundle,
        project_id: str,
        grid_index: int,
    ) -> str:
        """生成一张按项目方向映射后的 2K 三宫格大图（asset_type=nine_grid_image）。

        Args:
            bundle:      三宫格 PromptBundle（target_type='nine_grid_image'）
            project_id:  所属项目 ID
            grid_index:  第几张三宫格（从 1 开始）

        Returns:
            新建 Asset 的 asset_id（asset_type=nine_grid_image）
        """
        logger = get_project_logger(project_id, module="tools.image_generation")

        adapter = get_image_provider(bundle.provider)

        params = {**(bundle.params or {})}
        width = int(params.get("width", 3072))
        height = int(params.get("height", 3072))
        target_cell_aspect_ratio = str(
            params.get("target_cell_aspect_ratio") or params.get("aspect_ratio") or "9:16"
        )
        grid_rows = int(params.get("grid_rows") or 1)
        grid_columns = int(params.get("grid_columns") or 3)
        if grid_rows != 1 or grid_columns != 3:
            grid_rows, grid_columns = 1, 3
        if width % grid_columns != 0 or height % grid_rows != 0:
            raise ImageGenerationError(
                f"三宫格尺寸必须可被 1x3 均匀切分，当前 width={width} height={height}",
                code="invalid_nine_grid_size",
            )

        logger.info(
            f"三宫格生图开始: provider={bundle.provider!r} grid_index={grid_index} "
            f"size={params.get('size', f'{width}x{height}')!r} "
            f"resolution={params.get('resolution', '2K')!r} "
            f"orientation={params.get('orientation', 'square')!r}",
            event_type="nine_grid_generation_start",
        )
        provider_started_at = time.monotonic()
        try:
            result = await adapter.generate(
                prompt=bundle.positive_prompt,
                negative_prompt=bundle.negative_prompt,
                params=params,
            )
        except ImageGenerationError:
            raise
        except Exception as exc:
            raise ImageGenerationError(
                f"三宫格生图意外失败: {exc}", code="unexpected_error"
            ) from exc

        if not result.image_url:
            raise ImageGenerationError(
                "三宫格生图 API 返回空 URL", code="empty_url"
            )
        logger.info(
            f"三宫格 provider 返回图片 URL: grid_index={grid_index} "
            f"url={result.image_url[:160]!r} elapsed={time.monotonic() - provider_started_at:.2f}s",
            event_type="nine_grid_generation_result_ready",
        )

        download_started_at = time.monotonic()
        image_bytes = await self._download_image(result.image_url, timeout=120)
        logger.info(
            f"三宫格图片下载完成: grid_index={grid_index} size_bytes={len(image_bytes)} "
            f"elapsed={time.monotonic() - download_started_at:.2f}s",
            event_type="nine_grid_download_done",
        )

        # 上传 MinIO
        asset_id = generate_ulid()
        suffix = self._infer_suffix(result.image_url)
        filename = f"grid_{grid_index:03d}{suffix}"
        object_key = (
            f"projects/{project_id}/assets/nine_grid/{asset_id}/{filename}"
        )
        content_type = "image/png" if suffix == ".png" else "image/jpeg"

        storage = get_storage()
        upload_started_at = time.monotonic()
        await storage.async_upload_bytes(
            object_key, image_bytes, content_type=content_type
        )
        storage_uri = storage.get_permanent_url(object_key)
        logger.info(
            f"三宫格上传对象存储完成: grid_index={grid_index} asset_id={asset_id!r} "
            f"object_key={object_key!r} elapsed={time.monotonic() - upload_started_at:.2f}s",
            event_type="nine_grid_upload_done",
        )

        # 落库 Asset
        async with UnitOfWork() as uow:
            asset = Asset(
                id=asset_id,
                project_id=project_id,
                asset_type="nine_grid_image",
                bucket_name=storage.default_bucket,
                object_key=object_key,
                storage_uri=storage_uri,
                mime_type=content_type,
                size_bytes=len(image_bytes),
                width=result.width or width,
                height=result.height or height,
                metadata_={
                    "bundle_id": bundle.bundle_id,
                    "provider": bundle.provider,
                    "grid_index": grid_index,
                    "original_url": result.image_url,
                    "requested_size": params.get("size", f"{width}x{height}"),
                    "requested_resolution": params.get("resolution", "2K"),
                    "requested_orientation": params.get("orientation", "square"),
                    "target_cell_aspect_ratio": target_cell_aspect_ratio,
                    "grid_rows": grid_rows,
                    "grid_columns": grid_columns,
                },
            )
            await AssetRepository(uow.session).add(asset)
            await uow.flush()

        # 写本地副本（doc 21 §5.2 路径约定）
        try:
            store = LocalArtifactStore(project_id)
            local_path = store.planner.nine_grid_dir() / filename
            local_path.write_bytes(image_bytes)
            logger.info(
                f"三宫格本地副本写入完成: grid_index={grid_index} path={str(local_path)!r}",
                event_type="nine_grid_local_copy_done",
            )
        except Exception as exc:
            logger.warning(
                f"三宫格本地副本写入失败（不影响业务）: {exc}",
                event_type="nine_grid_local_copy_failed",
            )

        logger.info(
            f"三宫格生图完成: asset_id={asset_id!r} grid_index={grid_index} "
            f"size={len(image_bytes)} bytes",
            event_type="nine_grid_generation_done",
        )
        return asset_id

    async def split_and_persist_grid(
        self,
        parent_asset_id: str,
        project_id: str,
        grid_index: int,
    ) -> list[str]:
        """从三宫格大图切分 3 张 cell 图，每张作为 storyboard_frame asset 落库。

        Args:
            parent_asset_id:     三宫格大图 asset_id（asset_type=nine_grid_image）
            project_id:          所属项目 ID
            grid_index:          第几张三宫格（从 1 开始）

        Returns:
            3 个 asset_id 列表（按 cell_position 1-3 顺序）
        """
        from io import BytesIO

        from PIL import Image

        logger = get_project_logger(project_id, module="tools.image_generation")

        # 1. 读大图字节
        async with UnitOfWork() as uow:
            parent_asset = await AssetRepository(uow.session).get_by_id(parent_asset_id)
        if parent_asset is None:
            raise ImageGenerationError(
                f"三宫格大图 asset {parent_asset_id!r} 不存在",
                code="parent_asset_not_found",
            )
        target_cell_aspect_ratio = (
            parent_asset.metadata_ or {}
        ).get("target_cell_aspect_ratio") or (
            parent_asset.metadata_ or {}
        ).get("aspect_ratio") or "9:16"

        parent_access_url = await build_asset_access_url(parent_asset)
        if not parent_access_url:
            raise ImageGenerationError(
                f"三宫格大图 asset {parent_asset_id!r} 无可访问 URL",
                code="parent_asset_url_missing",
            )
        logger.info(
            f"开始读取三宫格大图并准备切分: grid_index={grid_index} "
            f"parent_asset_id={parent_asset_id!r} parent_url={parent_access_url[:160]!r}",
            event_type="nine_grid_split_parent_fetch_start",
        )
        parent_download_started_at = time.monotonic()
        parent_bytes = await self._download_image(parent_access_url, timeout=120)
        logger.info(
            f"三宫格大图读取完成: grid_index={grid_index} bytes={len(parent_bytes)} "
            f"elapsed={time.monotonic() - parent_download_started_at:.2f}s",
            event_type="nine_grid_split_parent_fetch_done",
        )

        # 2. PIL 切 3 张
        img = Image.open(BytesIO(parent_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        width, height = img.size
        cell_w = width // 3
        cell_h = height
        # 轻微向内裁切，避免模型生成的浅色分隔线/白边被直接切进 cell。
        inset_px = 1

        storage = get_storage()
        cell_asset_ids: list[str] = []

        for cell_position in range(1, 4):
            # 计算 cell 在大图中的坐标
            row = 0
            col = (cell_position - 1) % 3
            left = col * cell_w + inset_px
            top = row * cell_h + inset_px
            right = (col + 1) * cell_w - inset_px
            bottom = (row + 1) * cell_h - inset_px
            if right <= left or bottom <= top:
                left = col * cell_w
                top = row * cell_h
                right = left + cell_w
                bottom = top + cell_h

            cell_img = self._crop_to_aspect_ratio(
                img.crop((left, top, right, bottom)),
                str(target_cell_aspect_ratio),
            )
            buf = BytesIO()
            cell_img.save(buf, format="PNG")
            cell_bytes = buf.getvalue()
            cropped_width, cropped_height = cell_img.size

            # 上传 MinIO
            cell_asset_id = generate_ulid()
            cell_filename = f"grid_{grid_index:03d}_cell_{cell_position}.png"
            cell_object_key = (
                f"projects/{project_id}/assets/storyboard_frame/{cell_asset_id}/{cell_filename}"
            )
            await storage.async_upload_bytes(
                cell_object_key, cell_bytes, content_type="image/png"
            )
            cell_storage_uri = storage.get_permanent_url(cell_object_key)

            # 落库 Asset
            async with UnitOfWork() as uow:
                cell_asset = Asset(
                    id=cell_asset_id,
                    project_id=project_id,
                    asset_type="storyboard_frame",
                    bucket_name=storage.default_bucket,
                    object_key=cell_object_key,
                    storage_uri=cell_storage_uri,
                    mime_type="image/png",
                    size_bytes=len(cell_bytes),
                    width=cropped_width,
                    height=cropped_height,
                    metadata_={
                        "grid_index": grid_index,
                        "cell_position": cell_position,
                        "parent_asset_id": parent_asset_id,
                        "target_cell_aspect_ratio": target_cell_aspect_ratio,
                    },
                )
                await AssetRepository(uow.session).add(cell_asset)
                await uow.flush()

            # 写本地副本
            try:
                store = LocalArtifactStore(project_id)
                local_path = store.planner.storyboard_cells_dir() / cell_filename
                local_path.write_bytes(cell_bytes)
            except Exception as exc:
                logger.warning(
                    f"cell 本地副本写入失败（不影响业务）: {exc}",
                    event_type="nine_grid_cell_local_copy_failed",
                )

            cell_asset_ids.append(cell_asset_id)

        logger.info(
            f"三宫格切分完成: grid_index={grid_index} cells={len(cell_asset_ids)}",
            event_type="nine_grid_split_done",
        )
        return cell_asset_ids

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    async def _download_image(url: str, timeout: int = 60) -> bytes:
        """下载图片字节。"""
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.content
            except httpx.TimeoutException as exc:
                raise ImageGenerationError(
                    f"下载生成图片超时: {url[:100]}", code="download_timeout"
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise ImageGenerationError(
                    f"下载生成图片失败 {exc.response.status_code}: {url[:100]}",
                    code="download_error",
                ) from exc
            except Exception as exc:
                raise ImageGenerationError(
                    f"下载图片意外失败: {exc}", code="download_unexpected"
                ) from exc

    @staticmethod
    def _infer_suffix(url: str) -> str:
        """从 URL 推断图片后缀，默认 .jpg。"""
        url_lower = url.lower().split("?")[0]
        if url_lower.endswith(".png"):
            return ".png"
        if url_lower.endswith(".webp"):
            return ".webp"
        return ".jpg"

    @staticmethod
    def _crop_to_aspect_ratio(img: "Image.Image", aspect_ratio: str) -> "Image.Image":
        """按目标比例中心裁剪，用于把三宫格 cell 归一到视频参考画幅。"""
        try:
            w_str, h_str = aspect_ratio.split(":", 1)
            ratio_w = float(w_str)
            ratio_h = float(h_str)
            if ratio_w <= 0 or ratio_h <= 0:
                return img
        except (TypeError, ValueError):
            return img

        width, height = img.size
        target_ratio = ratio_w / ratio_h
        current_ratio = width / height if height else target_ratio

        if abs(current_ratio - target_ratio) < 0.01:
            return img
        if current_ratio > target_ratio:
            new_width = max(1, int(round(height * target_ratio)))
            left = max(0, (width - new_width) // 2)
            return img.crop((left, 0, left + new_width, height))

        new_height = max(1, int(round(width / target_ratio)))
        top = max(0, (height - new_height) // 2)
        return img.crop((0, top, width, top + new_height))
