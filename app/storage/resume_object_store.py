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

    async def delete(self, *, bucket: str, object_key: str) -> None: ...

    def close(self) -> None: ...
