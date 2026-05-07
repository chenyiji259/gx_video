"""Asset Service — 资产上传与查询业务逻辑。

来源文档：doc 05 §9（资产接口）、doc 05 §9.3（对象存储 Key 规范）

上传流程（两步式，客户端直传对象存储）：
  Step 1 - upload_init():
    后端生成对象存储 PUT 预签名 URL（30 分钟有效），
    客户端直接 PUT 到对象存储，无需经后端中转（避免大文件占用后端带宽）。

  Step 2 - complete_upload():
    客户端上传完成后通知后端。
    后端从对象存储获取对象元信息（size、etag 等）、落库 Asset 记录，
    并触发 AssetSyncService 将文件副本同步到本地 01_input/ 目录。

对象存储 Key 规范（doc 05 §9.3）：
    projects/{project_id}/assets/{asset_type}/{asset_id}/{filename}

storage_uri 格式（DB 存储永久直链，API 返回签名链接）：
    DB: {storage_public_base_url}/projects/{project_id}/assets/{type}/{id}/{filename}
    API 响应: 动态生成的签名链接（presigned URL），有效期由 config.storage.presigned_expiry 控制
"""
from __future__ import annotations

import mimetypes
from typing import Optional

from app.core.logging import get_project_logger
from app.models.asset import Asset
from app.repositories.asset_repository import AssetRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork
from app.storage.storage_factory import get_storage
from app.utils.ids import generate_ulid

# 允许上传的 MIME 类型映射到 asset_type
_MIME_TO_ASSET_TYPE: dict[str, str] = {
    # 音频
    "audio/mpeg": "audio_original",
    "audio/mp3": "audio_original",
    "audio/wav": "audio_original",
    "audio/x-wav": "audio_original",
    "audio/flac": "audio_original",
    "audio/aac": "audio_original",
    "audio/ogg": "audio_original",
    "audio/mp4": "audio_original",
    # 图片
    "image/jpeg": "image_reference",
    "image/png": "image_reference",
    "image/webp": "image_reference",
    "image/gif": "image_reference",
}

# 允许的 asset_type 值（对应 models/asset.py 中的约束 + doc11 新增类型 + doc12 文本产物协议）
_VALID_ASSET_TYPES = frozenset([
    "audio_original", "audio_trimmed",
    "image_reference", "style_reference",
    "storyboard_frame", "clip_video",
    "export_video", "subtitle_file", "thumbnail",
    # doc11 新增：视觉圣经类型
    "character_reference",  # 角色定妆图（img2img 或 txt2img）
    "scene_reference",      # 场景参考图（txt2img）
    "prop_reference",       # 道具/细节参考图（可选）
    "audio_analysis", "creative_brief", "style_bible",
    "narrative_script", "scene_plan", "shot_plan",
    "visual_bible", "storyboard", "prompt_bundle", "timeline",
])

# 上传预签名 URL 有效期（秒），30 分钟
_UPLOAD_URL_EXPIRY_SECONDS = 1800


class AssetError(Exception):
    """资产业务异常。"""
    def __init__(self, message: str, code: str = "asset_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ImmutabilityViolationError(Exception):
    """资产不可变性违规异常（doc11 §16.3）。

    资产一旦落库，永远不允许修改，只允许创建新版本。
    违反守则将导致回滚、版本对比、stale 追溯、调试历史全部失效。
    """
    def __init__(self, asset_id: str) -> None:
        super().__init__(
            f"Asset {asset_id!r} 不允许修改，请使用 create_new_version() 创建新版本。"
        )
        self.asset_id = asset_id
        self.code = "immutability_violation"


def _asset_to_dict(asset: Asset, *, presigned_url: str = "") -> dict:
    """将 Asset ORM 对象转为 API 响应 dict。

    Args:
        presigned_url: 动态生成的签名链接。有值时覆盖 storage_uri 返回给前端。
    """
    return {
        "id": asset.id,
        "project_id": asset.project_id,
        "asset_type": asset.asset_type,
        "bucket_name": asset.bucket_name,
        "object_key": asset.object_key,
        "storage_uri": presigned_url or asset.storage_uri,
        "mime_type": asset.mime_type,
        "size_bytes": asset.size_bytes,
        "duration_ms": asset.duration_ms,
        "width": asset.width,
        "height": asset.height,
        "sha256": asset.sha256,
        "metadata": asset.metadata_,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }


async def _asset_to_dict_presigned(asset: Asset) -> dict:
    """返回带签名链接的 asset dict。

    私有 OSS 场景下，统一优先返回签名链接。
    签名生成失败时降级为永久直链。
    """
    if asset.object_key:
        try:
            storage = get_storage()
            presigned = await storage.async_get_presigned_url(
                asset.object_key,
                bucket=asset.bucket_name,
            )
            return _asset_to_dict(asset, presigned_url=presigned)
        except Exception:
            pass  # 降级为永久直链

    return _asset_to_dict(asset)


class AssetService:
    """资产上传与查询服务。

    所有操作必须携带 user_id + project_id（用户隔离）。
    资产 append-only：一旦落库不允许修改。
    """

    async def update_asset(self, asset_id: str, **kwargs: object) -> None:
        """禁止调用。资产不允许修改，请使用 create_new_version()。

        doc11 §16.3 资产不可变性强制。

        Raises:
            ImmutabilityViolationError: 必常抛出。
        """
        raise ImmutabilityViolationError(asset_id)

    # ------------------------------------------------------------------ #
    # Step 1：上传初始化 — 获取 MinIO 预签名 PUT URL
    # ------------------------------------------------------------------ #

    async def upload_init(
        self,
        project_id: str,
        user_id: str,
        filename: str,
        content_type: str,
        asset_type: Optional[str] = None,
    ) -> dict:
        """申请上传槽位，返回客户端直传所需的预签名 PUT URL。

        后端只负责：
          1. 验证项目归属
          2. 生成 asset_id 和 object_key（path 规范）
          3. 生成 MinIO PUT 预签名 URL

        Args:
            project_id:   目标项目 ID。
            user_id:      当前用户 ID（用于项目归属校验）。
            filename:     原始文件名（用于 object_key 后缀，最多取最后 128 字符）。
            content_type: 文件 MIME 类型。
            asset_type:   资产类型，为 None 时按 content_type 自动推断。

        Returns:
            dict 包含：
              asset_id    - 预生成的资产 ID（落库在 complete 步骤）
              upload_url  - MinIO PUT 预签名 URL（30 分钟有效）
              object_key  - MinIO 对象路径
              bucket_name - 目标 bucket
              expires_in  - URL 有效秒数

        Raises:
            AssetError: 项目不存在 / 文件类型不支持 / asset_type 非法。
        """
        # 1. 校验项目归属
        await self._assert_project_owned(project_id, user_id)

        # 2. 推断 asset_type
        resolved_type = asset_type or self._infer_asset_type(content_type, filename)
        if resolved_type not in _VALID_ASSET_TYPES:
            raise AssetError(
                f"不支持的 asset_type: {resolved_type!r}",
                code="validation_error",
            )

        # 3. 生成 asset_id 和 object_key
        asset_id = generate_ulid()
        safe_filename = filename[-128:].replace(" ", "_") if filename else "file"
        object_key = (
            f"projects/{project_id}/assets/{resolved_type}/{asset_id}/{safe_filename}"
        )

        # 4. 生成预签名 PUT URL（30 分钟，客户端直传）
        storage = get_storage()
        upload_url = await storage.async_get_upload_presigned_url(
            object_key,
            expiry_seconds=_UPLOAD_URL_EXPIRY_SECONDS,
        )
        bucket_name = storage.default_bucket

        logger = get_project_logger(project_id, module="services.asset")
        logger.info(
            f"Upload init: asset_id={asset_id!r} type={resolved_type!r} file={filename!r}",
            event_type="asset_upload_init",
        )

        return {
            "asset_id": asset_id,
            "upload_url": upload_url,
            "object_key": object_key,
            "bucket_name": bucket_name,
            "expires_in": _UPLOAD_URL_EXPIRY_SECONDS,
        }

    # ------------------------------------------------------------------ #
    # Step 2：上传完成 — 核验 + 落库 + 本地副本
    # ------------------------------------------------------------------ #

    async def complete_upload(
        self,
        project_id: str,
        user_id: str,
        asset_id: str,
        object_key: str,
        bucket_name: str,
        filename: str,
        content_type: str,
        asset_type: str,
        *,
        sha256: Optional[str] = None,
        duration_ms: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        extra_metadata: Optional[dict] = None,
    ) -> dict:
        """确认客户端已上传完毕，核验对象存在并落库 Asset 记录。

        执行步骤：
          1. 校验项目归属
          2. 从 MinIO 获取对象 stat（size、etag）
          3. 在 DB 事务内创建 Asset 记录
          4. 触发 AssetSyncService 同步本地追溯副本

        Args:
            project_id:    目标项目 ID。
            user_id:       当前用户 ID。
            asset_id:      upload_init 返回的 asset_id（已预生成）。
            object_key:    upload_init 返回的 object_key。
            bucket_name:   upload_init 返回的 bucket_name。
            filename:      原始文件名（写入 metadata）。
            content_type:  文件 MIME 类型。
            asset_type:    资产类型。
            sha256:        文件 SHA-256（可选，用于去重）。
            duration_ms:   音频/视频时长（可选）。
            width/height:  图片/视频尺寸（可选）。
            extra_metadata: 附加元数据。

        Returns:
            asset dict（含 storage_uri 永久直链）。

        Raises:
            AssetError: 项目不存在 / MinIO 对象不存在。
        """
        # 1. 校验项目归属
        await self._assert_project_owned(project_id, user_id)

        # 2. 从 MinIO 获取对象 stat（验证已上传 + 拿 size）
        storage = get_storage()
        try:
            meta = await storage.async_get_metadata(object_key, bucket=bucket_name)
            size_bytes = meta.size
        except Exception as exc:
            raise AssetError(
                f"MinIO 中未找到对象 {object_key!r}，请先完成文件上传。",
                code="not_found",
            ) from exc

        # 3. 构造永久直链 URL
        storage_uri = storage.get_permanent_url(object_key, bucket=bucket_name)

        # 4. 落库 Asset 记录（在事务内）
        metadata = {"original_filename": filename, **(extra_metadata or {})}
        async with UnitOfWork() as uow:
            repo = AssetRepository(uow.session)
            asset = Asset(
                id=asset_id,
                project_id=project_id,
                asset_type=asset_type,
                bucket_name=bucket_name,
                object_key=object_key,
                storage_uri=storage_uri,
                mime_type=content_type,
                size_bytes=size_bytes,
                duration_ms=duration_ms,
                width=width,
                height=height,
                sha256=sha256,
                metadata_=metadata,
            )
            await repo.add(asset)
            await uow.flush()
            await uow.session.refresh(asset)

        logger = get_project_logger(project_id, module="services.asset")
        logger.info(
            f"Asset complete: id={asset_id!r} type={asset_type!r} "
            f"size={size_bytes} uri={storage_uri!r}",
            event_type="asset_upload_complete",
        )

        # 5. 同步本地追溯副本（同步执行，保证追溯一致性）
        try:
            from app.services.asset_sync_service import AssetSyncService
            await AssetSyncService().sync(asset)
        except Exception as exc:
            # 副本写入失败不影响业务流程，记录 warning
            logger.warning(
                f"本地副本同步失败（不影响业务）: {exc}",
                event_type="asset_sync_failed",
            )

        return await _asset_to_dict_presigned(asset)

    async def upload_file_proxy(
        self,
        project_id: str,
        user_id: str,
        *,
        filename: str,
        content_type: str,
        data: bytes,
        asset_type: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> dict:
        """后端代理上传文件，避免浏览器直传 OSS 的 CORS/预检问题。"""
        await self._assert_project_owned(project_id, user_id)
        resolved_type = asset_type or self._infer_asset_type(content_type, filename)
        if resolved_type not in _VALID_ASSET_TYPES:
            raise AssetError(
                f"不支持的 asset_type: {resolved_type!r}",
                code="validation_error",
            )

        asset_id = generate_ulid()
        safe_filename = filename[-128:].replace(" ", "_") if filename else "file"
        object_key = (
            f"projects/{project_id}/assets/{resolved_type}/{asset_id}/{safe_filename}"
        )
        storage = get_storage()
        bucket_name = storage.default_bucket
        await storage.async_upload_bytes(object_key, data, content_type=content_type)
        meta = await storage.async_get_metadata(object_key, bucket=bucket_name)
        storage_uri = storage.get_permanent_url(object_key, bucket=bucket_name)

        async with UnitOfWork() as uow:
            repo = AssetRepository(uow.session)
            asset = Asset(
                id=asset_id,
                project_id=project_id,
                asset_type=resolved_type,
                bucket_name=bucket_name,
                object_key=object_key,
                storage_uri=storage_uri,
                mime_type=content_type,
                size_bytes=meta.size,
                width=width,
                height=height,
                metadata_={"original_filename": filename, "upload_mode": "backend_proxy"},
            )
            await repo.add(asset)
            await uow.flush()
            await uow.session.refresh(asset)

        logger = get_project_logger(project_id, module="services.asset")
        logger.info(
            f"Asset proxy upload: id={asset_id!r} type={resolved_type!r} "
            f"size={meta.size} uri={storage_uri!r}",
            event_type="asset_proxy_upload_complete",
        )
        try:
            from app.services.asset_sync_service import AssetSyncService
            await AssetSyncService().sync(asset)
        except Exception as exc:
            logger.warning(
                f"本地副本同步失败（不影响业务）: {exc}",
                event_type="asset_sync_failed",
            )
        return await _asset_to_dict_presigned(asset)

    # ------------------------------------------------------------------ #
    # 查询资产列表
    # ------------------------------------------------------------------ #

    async def list_assets(
        self,
        project_id: str,
        user_id: str,
        *,
        asset_type: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """查询项目下的资产列表。

        Args:
            project_id: 目标项目 ID。
            user_id:    当前用户 ID（用于归属校验）。
            asset_type: 过滤资产类型（None = 全部）。
            limit:      最多返回条数。

        Returns:
            asset dict 列表。
        """
        await self._assert_project_owned(project_id, user_id)

        async with UnitOfWork() as uow:
            repo = AssetRepository(uow.session)
            assets = await repo.list_by_project(
                project_id,
                asset_type=asset_type,
                limit=limit,
            )

        return [await _asset_to_dict_presigned(a) for a in assets]

    async def list_all_assets_for_user(
        self,
        user_id: str,
        *,
        asset_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """拉取该用户的所有资产。"""
        async with UnitOfWork() as uow:
            repo = AssetRepository(uow.session)
            assets = await repo.list_all_by_user(
                user_id,
                asset_type=asset_type,
                limit=limit,
            )
        return [await _asset_to_dict_presigned(a) for a in assets]

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #

    async def _assert_project_owned(self, project_id: str, user_id: str) -> None:
        """确保项目存在且属于该用户，否则抛 AssetError。"""
        async with UnitOfWork() as uow:
            repo = ProjectRepository(uow.session)
            project = await repo.get_by_id_for_user(project_id, user_id)
        if project is None:
            raise AssetError("项目不存在", code="not_found")

    @staticmethod
    def _infer_asset_type(content_type: str, filename: str) -> str:
        """根据 content_type 和文件名后缀推断 asset_type。"""
        ct = content_type.lower().split(";")[0].strip()
        if ct in _MIME_TO_ASSET_TYPE:
            return _MIME_TO_ASSET_TYPE[ct]

        # 兜底：尝试从文件名后缀推断
        guessed, _ = mimetypes.guess_type(filename)
        if guessed and guessed in _MIME_TO_ASSET_TYPE:
            return _MIME_TO_ASSET_TYPE[guessed]

        # 无法推断，返回原始 type 让上层校验
        return ct
