"""资产访问 URL 服务。

统一处理：
  - 前端展示用访问 URL
  - 外部模型/Provider 拉取用访问 URL
  - 私有 OSS 场景下的签名 URL 生成
"""
from __future__ import annotations

from typing import Iterable

from app.models.asset import Asset
from app.storage.storage_factory import get_storage


async def build_asset_access_url(asset: Asset | None) -> str | None:
    """为资产生成当前可访问 URL。

    私有 OSS 下统一返回签名 GET URL；若签名失败则降级为存库的 storage_uri。
    """
    if asset is None:
        return None
    if not asset.object_key:
        return asset.storage_uri or None

    try:
        storage = get_storage()
        return await storage.async_get_presigned_url(
            asset.object_key,
            bucket=asset.bucket_name,
        )
    except Exception:
        return asset.storage_uri or None


async def build_asset_access_url_map(assets: Iterable[Asset]) -> dict[str, str]:
    """批量生成 asset_id -> 访问 URL 映射。"""
    result: dict[str, str] = {}
    for asset in assets:
        url = await build_asset_access_url(asset)
        if url:
            result[asset.id] = url
    return result
