"""阿里云 OSS 对象存储适配器。"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import oss2

from app.core.config import get_config
from app.storage.object_storage import ObjectMetadata


class OSSAdapter:
    """阿里云 OSS 对象存储适配器。"""

    def __init__(self, config: Optional[object] = None) -> None:
        cfg = config or get_config().storage
        self._default_bucket: str = cfg.bucket
        self._presigned_expiry: int = cfg.presigned_expiry
        self._secure: bool = cfg.secure
        self._endpoint: str = self._normalize_endpoint(cfg.endpoint, cfg.secure)
        self._public_base_url: str = self._normalize_public_base_url(
            cfg.public_base_url,
            self._default_bucket,
            self._endpoint,
        )
        self._auth = oss2.Auth(cfg.access_key, cfg.secret_key)
        self._region: str = cfg.region
        self._client = self._build_bucket(self._default_bucket)

    @property
    def default_bucket(self) -> str:
        return self._default_bucket

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def public_base_url(self) -> str:
        return self._public_base_url

    def _bucket(self, bucket: Optional[str]) -> str:
        return bucket or self._default_bucket

    def _build_bucket(self, bucket: str) -> oss2.Bucket:
        return oss2.Bucket(self._auth, self._endpoint, bucket)

    def _get_bucket_client(self, bucket: Optional[str]) -> oss2.Bucket:
        bucket_name = self._bucket(bucket)
        if bucket_name == self._default_bucket:
            return self._client
        return self._build_bucket(bucket_name)

    @staticmethod
    def _normalize_endpoint(endpoint: str, secure: bool) -> str:
        endpoint = (endpoint or "").strip().rstrip("/")
        if endpoint.startswith(("http://", "https://")):
            return endpoint
        scheme = "https" if secure else "http"
        return f"{scheme}://{endpoint}"

    @staticmethod
    def _normalize_public_base_url(
        public_base_url: str,
        bucket: str,
        endpoint: str,
    ) -> str:
        base = (public_base_url or "").strip().rstrip("/")
        if base:
            return base
        endpoint_without_scheme = endpoint.split("://", 1)[-1].rstrip("/")
        return f"https://{bucket}.{endpoint_without_scheme}"

    def get_permanent_url(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> str:
        bucket_name = self._bucket(bucket)
        base = self._public_base_url
        if bucket_name != self._default_bucket:
            base = base.rstrip("/")
            base = f"{base}/{quote(bucket_name, safe='')}"
        return f"{base.rstrip('/')}/{quote(key, safe='/')}"

    def get_upload_presigned_url(
        self,
        key: str,
        expiry_seconds: int = 1800,
        *,
        bucket: Optional[str] = None,
    ) -> str:
        client = self._get_bucket_client(bucket)
        return client.sign_url("PUT", key, expiry_seconds)

    async def async_get_upload_presigned_url(
        self,
        key: str,
        expiry_seconds: int = 1800,
        *,
        bucket: Optional[str] = None,
    ) -> str:
        return await asyncio.to_thread(
            self.get_upload_presigned_url, key, expiry_seconds, bucket=bucket
        )

    def upload_file(
        self,
        key: str,
        file_path: Path,
        content_type: str = "application/octet-stream",
        *,
        bucket: Optional[str] = None,
    ) -> str:
        client = self._get_bucket_client(bucket)
        headers = {"Content-Type": content_type}
        client.put_object_from_file(key, str(file_path), headers=headers)
        return f"oss://{self._bucket(bucket)}/{key}"

    def upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        *,
        bucket: Optional[str] = None,
    ) -> str:
        client = self._get_bucket_client(bucket)
        headers = {"Content-Type": content_type}
        client.put_object(key, io.BytesIO(data), headers=headers)
        return f"oss://{self._bucket(bucket)}/{key}"

    def download_file(
        self,
        key: str,
        dest_path: Path,
        *,
        bucket: Optional[str] = None,
    ) -> Path:
        client = self._get_bucket_client(bucket)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        client.get_object_to_file(key, str(dest_path))
        return dest_path

    def download_bytes(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> bytes:
        client = self._get_bucket_client(bucket)
        response = client.get_object(key)
        try:
            return response.read()
        finally:
            response.close()

    def get_presigned_url(
        self,
        key: str,
        expiry_seconds: Optional[int] = None,
        *,
        bucket: Optional[str] = None,
        method: str = "GET",
    ) -> str:
        client = self._get_bucket_client(bucket)
        expires = expiry_seconds or self._presigned_expiry
        return client.sign_url(method.upper(), key, expires)

    def object_exists(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> bool:
        client = self._get_bucket_client(bucket)
        return client.object_exists(key)

    def get_metadata(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> ObjectMetadata:
        client = self._get_bucket_client(bucket)
        stat = client.head_object(key)
        headers = dict(getattr(stat, "headers", {}) or {})
        return ObjectMetadata(
            key=key,
            bucket=self._bucket(bucket),
            size=int(getattr(stat, "content_length", 0) or 0),
            content_type=getattr(stat, "content_type", "") or headers.get("Content-Type", "application/octet-stream"),
            etag=getattr(stat, "etag", "") or "",
            extra=headers,
        )

    def delete_object(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> None:
        client = self._get_bucket_client(bucket)
        client.delete_object(key)

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
            self.get_presigned_url, key, expiry_seconds, bucket=bucket, method=method
        )

    async def async_object_exists(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> bool:
        return await asyncio.to_thread(self.object_exists, key, bucket=bucket)

    async def async_get_metadata(
        self,
        key: str,
        *,
        bucket: Optional[str] = None,
    ) -> ObjectMetadata:
        return await asyncio.to_thread(self.get_metadata, key, bucket=bucket)

    def delete_prefix(self, prefix: str, *, bucket: Optional[str] = None) -> int:
        client = self._get_bucket_client(bucket)
        object_keys: list[str] = []
        deleted_count = 0
        for item in oss2.ObjectIterator(client, prefix=prefix):
            if getattr(item, "is_prefix", lambda: False)():
                continue
            object_keys.append(item.key)
            if len(object_keys) >= 1000:
                result = client.batch_delete_objects(object_keys)
                deleted_count += len(result.deleted_keys or [])
                object_keys.clear()
        if object_keys:
            result = client.batch_delete_objects(object_keys)
            deleted_count += len(result.deleted_keys or [])
        return deleted_count

    async def async_delete_prefix(self, prefix: str, *, bucket: Optional[str] = None) -> int:
        return await asyncio.to_thread(self.delete_prefix, prefix, bucket=bucket)
