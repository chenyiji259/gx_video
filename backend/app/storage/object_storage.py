"""对象存储抽象接口（Object Storage Abstraction）。

工程约束（doc 03 / doc 08）：
  对象存储层统一封装为 ObjectStorageAdapter。
  第一版使用 MinIO，后续可无业务层改动地替换为 S3 / 阿里云 OSS。

接口定义使用 Python Protocol，实现类无需显式继承。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Optional, Protocol, runtime_checkable


@dataclass
class ObjectMetadata:
    """对象元信息。"""
    key: str
    bucket: str
    size: int              # 字节数
    content_type: str
    etag: str
    extra: dict[str, Any]  # provider 特有字段


@runtime_checkable
class ObjectStorageAdapter(Protocol):
    """对象存储统一接口协议。

    所有实现类（MinIO、S3 等）必须实现以下方法。
    """

    def upload_file(
        self,
        key: str,
        file_path: Path,
        content_type: str = "application/octet-stream",
        *,
        bucket: Optional[str] = None,
    ) -> str:
        """上传本地文件到对象存储。

        Args:
            key: 对象存储中的 key（路径）。
            file_path: 本地文件路径。
            content_type: MIME 类型。
            bucket: 指定 bucket，为 None 时使用默认 bucket。

        Returns:
            对象在存储中的完整 URI（如 s3://bucket/key）。
        """
        ...

    def upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        *,
        bucket: Optional[str] = None,
    ) -> str:
        """上传字节数据到对象存储。

        Returns:
            对象 URI。
        """
        ...

    def download_file(
        self,
        key: str,
        dest_path: Path,
        *,
        bucket: Optional[str] = None,
    ) -> Path:
        """下载对象到本地文件。

        Returns:
            下载后的本地文件路径。
        """
        ...

    def download_bytes(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> bytes:
        """下载对象为字节数据。"""
        ...

    def get_presigned_url(
        self,
        key: str,
        expiry_seconds: Optional[int] = None,
        *,
        bucket: Optional[str] = None,
        method: str = "GET",
    ) -> str:
        """生成对象的预签名访问 URL。

        Args:
            key: 对象 key。
            expiry_seconds: URL 有效秒数，为 None 时使用配置默认值。
            bucket: 指定 bucket。
            method: HTTP 方法，默认 GET（下载）。

        Returns:
            预签名 URL 字符串。
        """
        ...

    def object_exists(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> bool:
        """检查对象是否存在。"""
        ...

    def get_metadata(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> ObjectMetadata:
        """获取对象元信息。"""
        ...

    def delete_object(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> None:
        """删除对象。"""
        ...
