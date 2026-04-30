"""MinIO 对象存储适配器。

工程约束（doc 03 / doc 08）：
  第一版优先使用 MinIO，便于本地开发、测试和私有部署。
  通过 ObjectStorageAdapter Protocol 封装，业务层无感知切换 provider。

所有同步 MinIO SDK 调用通过 asyncio.to_thread 包装，避免阻塞事件循环。
"""
from __future__ import annotations

import asyncio
import io
from datetime import timedelta
from pathlib import Path
from typing import Optional

from minio import Minio
from minio.error import S3Error

from app.core.config import get_config
from app.storage.object_storage import ObjectMetadata


class MinIOAdapter:
    """MinIO 对象存储适配器，实现 ObjectStorageAdapter 协议。

    用法（同步）：
        adapter = MinIOAdapter()
        uri = adapter.upload_file("audio/proj_abc/track.mp3", Path("/tmp/track.mp3"))

    用法（异步）：
        uri = await adapter.async_upload_file("audio/proj_abc/track.mp3", Path("/tmp/track.mp3"))

    永久直链（需 bucket 设置公开读权限）：
        url = adapter.get_permanent_url("projects/proj_abc/assets/audio_original/xxx/track.mp3")
        # 返回 http://10.60.1.102:9000/vidmuse/projects/proj_abc/.../track.mp3
    """

    def __init__(self, config: Optional[object] = None) -> None:
        cfg = config or get_config().storage
        self._default_bucket: str = cfg.bucket
        self._presigned_expiry: int = cfg.presigned_expiry
        self._endpoint: str = cfg.endpoint   # 保存供 get_permanent_url 使用
        self._secure: bool = cfg.secure
        self._client = Minio(
            cfg.endpoint,
            access_key=cfg.access_key,
            secret_key=cfg.secret_key,
            secure=cfg.secure,
            region=cfg.region,
        )

    # ------------------------------------------------------------------ #
    # 公共属性
    # ------------------------------------------------------------------ #

    @property
    def default_bucket(self) -> str:
        """返回默认 bucket 名称。"""
        return self._default_bucket

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #

    def _bucket(self, bucket: Optional[str]) -> str:
        return bucket or self._default_bucket

    def _ensure_bucket(self, bucket: str) -> None:
        """确保 bucket 存在，不存在则创建。"""
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)

    # ------------------------------------------------------------------ #
    # 永久直链 URL（无过期，需 bucket 公开读）
    # ------------------------------------------------------------------ #

    def get_permanent_url(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> str:
        """生成资产永久直链 URL（不含签名，无过期时间）。

        前提：MinIO bucket 必须设置公开读权限，执行一次即可：
            mc alias set local http://10.60.1.102:9000 <access_key> <secret_key>
            mc anonymous set public local/vidmuse

        Args:
            key:    MinIO 对象路径（不含 bucket 前缀）。
            bucket: 指定 bucket，默认使用配置中的 default bucket。

        Returns:
            http(s)://{endpoint}/{bucket}/{key} 格式的永久 URL。
        """
        b = self._bucket(bucket)
        scheme = "https" if self._secure else "http"
        return f"{scheme}://{self._endpoint}/{b}/{key}"

    # ------------------------------------------------------------------ #
    # 上传预签名 PUT（客户端直传 MinIO，30 分钟有效）
    # ------------------------------------------------------------------ #

    def get_upload_presigned_url(
        self,
        key: str,
        expiry_seconds: int = 1800,
        *,
        bucket: Optional[str] = None,
    ) -> str:
        """生成上传用预签名 PUT URL（客户端直传，避免大文件经后端中转）。

        Args:
            key:            MinIO 对象路径。
            expiry_seconds: URL 有效期（默认 30 分钟）。
            bucket:         指定 bucket。

        Returns:
            预签名 PUT URL 字符串。
        """
        b = self._bucket(bucket)
        self._ensure_bucket(b)
        return self._client.presigned_put_object(
            b, key, expires=timedelta(seconds=expiry_seconds)
        )

    async def async_get_upload_presigned_url(
        self,
        key: str,
        expiry_seconds: int = 1800,
        *,
        bucket: Optional[str] = None,
    ) -> str:
        """异步版本：生成上传用预签名 PUT URL。"""
        return await asyncio.to_thread(
            self.get_upload_presigned_url, key, expiry_seconds, bucket=bucket
        )

    # ------------------------------------------------------------------ #
    # 同步 API
    # ------------------------------------------------------------------ #

    def upload_file(
        self,
        key: str,
        file_path: Path,
        content_type: str = "application/octet-stream",
        *,
        bucket: Optional[str] = None,
    ) -> str:
        """上传本地文件。"""
        b = self._bucket(bucket)
        self._ensure_bucket(b)
        self._client.fput_object(b, key, str(file_path), content_type=content_type)
        return f"minio://{b}/{key}"

    def upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        *,
        bucket: Optional[str] = None,
    ) -> str:
        """上传字节数据。"""
        b = self._bucket(bucket)
        self._ensure_bucket(b)
        self._client.put_object(
            b, key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return f"minio://{b}/{key}"

    def download_file(
        self,
        key: str,
        dest_path: Path,
        *,
        bucket: Optional[str] = None,
    ) -> Path:
        """下载对象到本地文件。"""
        b = self._bucket(bucket)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        self._client.fget_object(b, key, str(dest_path))
        return dest_path

    def download_bytes(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> bytes:
        """下载对象为字节数据。"""
        b = self._bucket(bucket)
        response = self._client.get_object(b, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def get_presigned_url(
        self,
        key: str,
        expiry_seconds: Optional[int] = None,
        *,
        bucket: Optional[str] = None,
        method: str = "GET",
    ) -> str:
        """生成预签名 URL。"""
        b = self._bucket(bucket)
        expiry = timedelta(seconds=expiry_seconds or self._presigned_expiry)
        if method.upper() == "GET":
            return self._client.presigned_get_object(b, key, expires=expiry)
        return self._client.presigned_put_object(b, key, expires=expiry)

    def object_exists(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> bool:
        """检查对象是否存在。"""
        b = self._bucket(bucket)
        try:
            self._client.stat_object(b, key)
            return True
        except S3Error as e:
            if e.code == "NoSuchKey":
                return False
            raise

    def get_metadata(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> ObjectMetadata:
        """获取对象元信息。"""
        b = self._bucket(bucket)
        stat = self._client.stat_object(b, key)
        return ObjectMetadata(
            key=key,
            bucket=b,
            size=stat.size,
            content_type=stat.content_type or "application/octet-stream",
            etag=stat.etag or "",
            extra=dict(stat.metadata or {}),
        )

    def delete_object(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> None:
        """删除对象。"""
        b = self._bucket(bucket)
        self._client.remove_object(b, key)

    # ------------------------------------------------------------------ #
    # 异步包装（用于 FastAPI / async 上下文）
    # ------------------------------------------------------------------ #

    async def async_upload_file(
        self,
        key: str,
        file_path: Path,
        content_type: str = "application/octet-stream",
        *,
        bucket: Optional[str] = None,
    ) -> str:
        return await asyncio.to_thread(
            self.upload_file, key, file_path, content_type, bucket=bucket
        )

    async def async_upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        *,
        bucket: Optional[str] = None,
    ) -> str:
        return await asyncio.to_thread(
            self.upload_bytes, key, data, content_type, bucket=bucket
        )

    async def async_download_bytes(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> bytes:
        return await asyncio.to_thread(self.download_bytes, key, bucket=bucket)

    async def async_get_presigned_url(
        self,
        key: str,
        expiry_seconds: Optional[int] = None,
        *,
        bucket: Optional[str] = None,
        method: str = "GET",
    ) -> str:
        return await asyncio.to_thread(
            self.get_presigned_url, key, expiry_seconds,
            bucket=bucket, method=method,
        )

    async def async_object_exists(self, key: str, *, bucket: Optional[str] = None) -> bool:
        return await asyncio.to_thread(self.object_exists, key, bucket=bucket)

    async def async_get_metadata(self, key: str, *, bucket: Optional[str] = None) -> ObjectMetadata:
        return await asyncio.to_thread(self.get_metadata, key, bucket=bucket)

    # ------------------------------------------------------------------ #
    # 批量删除（用于项目清理）
    # ------------------------------------------------------------------ #

    def delete_prefix(self, prefix: str, *, bucket: Optional[str] = None) -> int:
        """删除指定前缀下的所有对象（递归）。

        用于项目删除时清理 MinIO 中的全部产物。

        Args:
            prefix: 对象路径前缀，例如 "projects/{project_id}/"。
            bucket: 指定 bucket，默认使用配置中的 default bucket。

        Returns:
            实际删除的对象数量（0 表示无对象或 bucket 不存在）。
        """
        b = self._bucket(bucket)
        try:
            objects = list(self._client.list_objects(b, prefix=prefix, recursive=True))
            count = 0
            for obj in objects:
                try:
                    self._client.remove_object(b, obj.object_name)
                    count += 1
                except S3Error:
                    pass  # 单个对象删除失败不中断整体清理
            return count
        except S3Error:
            return 0

    async def async_delete_prefix(self, prefix: str, *, bucket: Optional[str] = None) -> int:
        """异步版本：批量删除指定前缀下的所有对象。"""
        return await asyncio.to_thread(self.delete_prefix, prefix, bucket=bucket)


# 全局单例，懒加载
_adapter: Optional[MinIOAdapter] = None


def get_storage() -> MinIOAdapter:
    """返回全局 MinIO 适配器单例。"""
    global _adapter
    if _adapter is None:
        _adapter = MinIOAdapter()
    return _adapter
