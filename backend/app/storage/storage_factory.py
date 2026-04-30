"""统一存储入口。"""
from __future__ import annotations

from typing import Optional

from app.storage.oss_adapter import OSSAdapter

_adapter: Optional[OSSAdapter] = None


def get_storage() -> OSSAdapter:
    """返回全局 OSS 存储适配器单例。"""
    global _adapter
    if _adapter is None:
        _adapter = OSSAdapter()
    return _adapter
