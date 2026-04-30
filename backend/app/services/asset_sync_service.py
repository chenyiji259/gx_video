"""Asset Sync Service — 上传后本地追溯副本同步。

来源文档：doc 08 §8（本地产物保存规范）

职责：
  在资产上传完成（complete_upload）后，
  将对象存储中的文件下载一份副本到本地 data/projects/{id}/01_input/，
  同时写入元数据 JSON 供调试和问题排查使用。

设计决策：
  - 同步执行（不走 TaskWorker）：轻量 IO，保持追溯与落库强一致
  - 仅在 01_input/ 存放用户上传的原始输入资产（音频、参考图）
  - 其他类型资产（AI生成的 clip、storyboard 等）由各自服务负责同步
  - 副本文件命名：{asset_type}_{asset_id}_{timestamp}.{ext}
  - 元数据 JSON 命名：{asset_type}_{asset_id}_meta_{timestamp}.json
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from app.core.logging import get_project_logger
from app.models.asset import Asset
from app.storage.local_artifact_store import LocalArtifactStore
from app.storage.storage_factory import get_storage
from app.storage.path_planner import ArtifactStage

# 只同步这几类资产到 01_input/（用户上传的输入素材）
_SYNC_ASSET_TYPES = frozenset(["audio_original", "image_reference", "style_reference"])


class AssetSyncService:
    """将对象存储资产副本同步到本地追溯目录。"""

    async def sync(self, asset: Asset) -> Optional[Path]:
        """从对象存储下载资产副本到本地 01_input/，并写入元数据 JSON。

        只同步 audio_original / image_reference / style_reference 类型。
        其他类型（clip_video、storyboard_frame 等）由各自生成服务负责追溯。

        Args:
            asset: 已落库的 Asset ORM 对象。

        Returns:
            本地副本文件路径（若跳过同步则返回 None）。
        """
        if asset.asset_type not in _SYNC_ASSET_TYPES:
            return None

        logger = get_project_logger(asset.project_id, module="services.asset_sync")
        store = LocalArtifactStore(asset.project_id)

        # 推断文件扩展名
        ext = self._guess_ext(asset.mime_type, asset.object_key)

        # 生成本地副本路径
        # 命名：{asset_type}_{asset_id}.{ext}（无时间戳，因为 asset_id 已经唯一）
        dest_path = store.planner.stage_dir(ArtifactStage.INPUT, create=True) / (
            f"{asset.asset_type}_{asset.id}.{ext}"
        )

        # 从对象存储下载（同步 IO 包装为异步）
        storage = get_storage()
        try:
            await asyncio.to_thread(
                storage.download_file,
                asset.object_key,
                dest_path,
                bucket=asset.bucket_name,
            )
        except Exception as exc:
            logger.warning(
                f"对象存储下载失败: key={asset.object_key!r} err={exc}",
                event_type="asset_sync_download_failed",
            )
            raise

        # 写入元数据 JSON
        meta = {
            "asset_id": asset.id,
            "asset_type": asset.asset_type,
            "project_id": asset.project_id,
            "object_key": asset.object_key,
            "bucket_name": asset.bucket_name,
            "storage_uri": asset.storage_uri,
            "mime_type": asset.mime_type,
            "size_bytes": asset.size_bytes,
            "duration_ms": asset.duration_ms,
            "sha256": asset.sha256,
            "original_filename": (asset.metadata_ or {}).get("original_filename", ""),
            "local_copy": str(dest_path),
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
        }
        store.write_json(
            ArtifactStage.INPUT,
            f"{asset.asset_type}_{asset.id}_meta",
            meta,
        )

        logger.info(
            f"本地副本已写入: {dest_path}",
            event_type="asset_sync_complete",
        )
        return dest_path

    @staticmethod
    def _guess_ext(mime_type: str, object_key: str) -> str:
        """从 MIME 类型或 object_key 后缀推断文件扩展名。"""
        _MIME_EXT: dict[str, str] = {
            "audio/mpeg": "mp3",
            "audio/mp3": "mp3",
            "audio/wav": "wav",
            "audio/x-wav": "wav",
            "audio/flac": "flac",
            "audio/aac": "aac",
            "audio/ogg": "ogg",
            "audio/mp4": "m4a",
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
            "image/gif": "gif",
        }
        ct = mime_type.lower().split(";")[0].strip()
        if ct in _MIME_EXT:
            return _MIME_EXT[ct]
        # 从 object_key 取后缀
        suffix = Path(object_key).suffix.lstrip(".")
        return suffix or "bin"
