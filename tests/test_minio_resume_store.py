"""MinIO 简历对象存储测试，不连接真实服务。"""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from app.storage.minio_resume_store import MinioResumeObjectStore
from app.storage.resume_object_store import parsed_resume_object_key


class FakeMinioClient:
    """记录 MinIO SDK 调用参数。"""

    def __init__(self) -> None:
        self.bucket_created: tuple[str, str | None] | None = None
        self.saved_objects: dict[str, dict[str, Any]] = {}
        self.deleted: list[tuple[str, str]] = []

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
        metadata: dict[str, str] | None = None,
    ) -> Any:
        self.saved_objects[object_key] = {
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

    def get_object(self, bucket: str, object_key: str) -> Any:
        assert bucket == "jobpilot-resumes"
        if object_key.endswith(".resume.json"):
            return FakeObjectResponse(self.saved_objects[object_key]["content"])
        assert object_key.endswith(".pdf")
        return FakeObjectResponse(b"%PDF-staged")

    def remove_object(self, bucket: str, object_key: str) -> None:
        self.deleted.append((bucket, object_key))


class FakeObjectResponse:
    """模拟 MinIO 流式响应并记录连接释放。"""

    def __init__(self, content: bytes) -> None:
        self._content = content
        self.closed = False
        self.released = False

    def read(self) -> bytes:
        return self._content

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


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
        saved_pdf = client.saved_objects[metadata.object_key]
        assert saved_pdf["content"] == content
        assert saved_pdf["metadata"] == {"sha256": "a" * 64}
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

        staged_content = await store.read(
            bucket=metadata.bucket,
            object_key=metadata.object_key,
        )
        assert staged_content == b"%PDF-staged"

        parsed_content = b'{"skills":["Java"]}'
        await store.save_parsed_resume(
            bucket=metadata.bucket,
            pdf_object_key=metadata.object_key,
            content=parsed_content,
        )
        parsed_key = parsed_resume_object_key(metadata.object_key)
        assert client.saved_objects[parsed_key]["content"] == parsed_content
        assert client.saved_objects[parsed_key]["content_type"] == "application/json"
        assert await store.read_parsed_resume(
            bucket=metadata.bucket,
            pdf_object_key=metadata.object_key,
        ) == parsed_content

        await store.delete_resume(
            bucket=metadata.bucket,
            pdf_object_key=metadata.object_key,
        )
        assert client.deleted == [
            (metadata.bucket, metadata.object_key),
            (metadata.bucket, parsed_key),
        ]

    asyncio.run(run())
