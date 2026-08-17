"""完整简历对象存储抽象。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ResumeObjectMetadata:
    """写入对象存储后需要持久化到 MySQL 的稳定元数据。"""

    bucket: str
    object_key: str
    storage_uri: str
    etag: str | None
    size_bytes: int
    content_type: str


class ResumeObjectStore(Protocol):
    """原始简历文件对象存储的最小接口。"""

    async def save(
        self,
        *,
        user_id: int,
        filename: str,
        content: bytes,
        content_type: str,
        doc_hash: str,
    ) -> ResumeObjectMetadata: ...

    async def create_download_url(self, *, bucket: str, object_key: str) -> str: ...

    async def read(self, *, bucket: str, object_key: str) -> bytes: ...

    async def save_parsed_resume(
        self,
        *,
        bucket: str,
        pdf_object_key: str,
        content: bytes,
    ) -> None: ...

    async def read_parsed_resume(self, *, bucket: str, pdf_object_key: str) -> bytes: ...

    async def delete_resume(self, *, bucket: str, pdf_object_key: str) -> None: ...

    def close(self) -> None: ...


def parsed_resume_object_key(pdf_object_key: str) -> str:
    """由 PDF 对象键稳定推导结构化 Resume JSON 对象键。"""
    suffix = ".pdf"
    base = (
        pdf_object_key[: -len(suffix)]
        if pdf_object_key.lower().endswith(suffix)
        else pdf_object_key
    )
    return f"{base}.resume.json"
