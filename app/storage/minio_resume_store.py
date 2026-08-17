"""MinIO 原始简历对象存储。"""

import asyncio
from io import BytesIO
from threading import RLock
from typing import Any
from uuid import uuid4

from app.storage.resume_object_store import ResumeObjectMetadata


class MinioResumeObjectStore:
    """将原始 PDF 保存为私有 MinIO 对象，并按需生成短时下载地址。"""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool,
        bucket: str,
        region: str | None,
        presigned_url_ttl_seconds: int,
        client: Any | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._secure = secure
        self._bucket = bucket
        self._region = region
        self._presigned_url_ttl_seconds = presigned_url_ttl_seconds
        self._client = client
        self._client_lock = RLock()
        self._bucket_ready = False

    def _get_client(self) -> Any:
        """延迟创建客户端，避免未使用文件功能时连接 MinIO。"""
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is None:
                if not self._access_key or not self._secret_key:
                    raise RuntimeError("MinIO access key and secret key are required")
                from minio import Minio

                self._client = Minio(
                    self._endpoint,
                    access_key=self._access_key,
                    secret_key=self._secret_key,
                    secure=self._secure,
                    region=self._region,
                )
        return self._client

    def _ensure_bucket(self) -> None:
        """首次写入前确保私有 bucket 存在。"""
        if self._bucket_ready:
            return
        with self._client_lock:
            if self._bucket_ready:
                return
            client = self._get_client()
            if not client.bucket_exists(self._bucket):
                client.make_bucket(self._bucket, location=self._region)
            self._bucket_ready = True

    async def save(
        self,
        *,
        user_id: int,
        filename: str,
        content: bytes,
        content_type: str,
        doc_hash: str,
    ) -> ResumeObjectMetadata:
        """保存原始 PDF，并返回适合写入 MySQL 的稳定地址信息。"""
        return await asyncio.to_thread(
            self._save_sync,
            user_id,
            filename,
            content,
            content_type,
            doc_hash,
        )

    def _save_sync(
        self,
        user_id: int,
        filename: str,
        content: bytes,
        content_type: str,
        doc_hash: str,
    ) -> ResumeObjectMetadata:
        del filename
        self._ensure_bucket()
        object_key = f"users/{user_id}/resumes/{uuid4().hex}.pdf"
        result = self._get_client().put_object(
            self._bucket,
            object_key,
            BytesIO(content),
            length=len(content),
            content_type=content_type,
            metadata={"sha256": doc_hash},
        )
        return ResumeObjectMetadata(
            bucket=self._bucket,
            object_key=object_key,
            storage_uri=f"s3://{self._bucket}/{object_key}",
            etag=getattr(result, "etag", None),
            size_bytes=len(content),
            content_type=content_type,
        )

    async def create_download_url(self, *, bucket: str, object_key: str) -> str:
        """为私有对象生成短时 GET 地址。"""
        from datetime import timedelta

        return await asyncio.to_thread(
            self._get_client().presigned_get_object,
            bucket,
            object_key,
            expires=timedelta(seconds=self._presigned_url_ttl_seconds),
        )

    async def delete(self, *, bucket: str, object_key: str) -> None:
        """删除跨存储失败时遗留的对象。"""
        await asyncio.to_thread(self._get_client().remove_object, bucket, object_key)

    def close(self) -> None:
        """释放 MinIO SDK 使用的 HTTP 连接池。"""
        if self._client is None:
            return
        pool = getattr(self._client, "_http", None)
        clear = getattr(pool, "clear", None)
        if callable(clear):
            clear()
        self._client = None
        self._bucket_ready = False
