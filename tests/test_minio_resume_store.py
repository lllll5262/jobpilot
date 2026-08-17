"""MinIO 简历对象存储测试，不连接真实服务。"""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from app.storage.minio_resume_store import MinioResumeObjectStore


class FakeMinioClient:
    """记录 MinIO SDK 调用参数。"""

    def __init__(self) -> None:
        self.bucket_created: tuple[str, str | None] | None = None
        self.saved: dict[str, Any] | None = None
        self.deleted: tuple[str, str] | None = None

    def bucket_exists(self, bucket: str) -> bool:
        return False

    def make_bucket(self, bucket: str, *, location: str | None) -> None:
        self.bucket_created = (bucket, location)

    def put_object(
        self,
        bucket: str,
        object_key: str,
        data: Any,
        *,
        length: int,
        content_type: str,
        metadata: dict[str, str],
    ) -> Any:
        self.saved = {
            "bucket": bucket,
            "object_key": object_key,
            "content": data.read(),
            "length": length,
            "content_type": content_type,
            "metadata": metadata,
        }
        return SimpleNamespace(etag="etag-123")

    def presigned_get_object(
        self,
        bucket: str,
        object_key: str,
        *,
        expires: timedelta,
    ) -> str:
        assert expires == timedelta(minutes=15)
        return f"https://minio.example/{bucket}/{object_key}?signature=test"

    def remove_object(self, bucket: str, object_key: str) -> None:
        self.deleted = (bucket, object_key)


def test_minio_store_saves_private_pdf_and_returns_stable_metadata() -> None:
    """对象键不暴露原文件名，MySQL 可保存稳定的 s3 地址。"""

    async def run() -> None:
        client = FakeMinioClient()
        store = MinioResumeObjectStore(
            endpoint="minio:9000",
            access_key="access",
            secret_key="secret",
            secure=False,
            bucket="jobpilot-resumes",
            region=None,
            presigned_url_ttl_seconds=900,
            client=client,
        )
        content = b"%PDF-test"
        metadata = await store.save(
            user_id=7,
            filename="candidate.pdf",
            content=content,
            content_type="application/pdf",
            doc_hash="a" * 64,
        )

        assert client.bucket_created == ("jobpilot-resumes", None)
        assert client.saved is not None
        assert client.saved["content"] == content
        assert client.saved["metadata"] == {"sha256": "a" * 64}
        assert metadata.object_key.startswith("users/7/resumes/")
        assert metadata.object_key.endswith(".pdf")
        assert metadata.storage_uri == (
            f"s3://jobpilot-resumes/{metadata.object_key}"
        )
        assert metadata.etag == "etag-123"

        download_url = await store.create_download_url(
            bucket=metadata.bucket,
            object_key=metadata.object_key,
        )
        assert "signature=test" in download_url

        await store.delete(bucket=metadata.bucket, object_key=metadata.object_key)
        assert client.deleted == (metadata.bucket, metadata.object_key)

    asyncio.run(run())
