"""简历父子分块与 Milvus 索引编排。"""

from contextlib import suppress
from typing import Protocol

from app.schemas.resume_vector import ResumeChunkMatch
from app.services.resume_chunking_service import ResumeChunk, ResumeChunkingService


class ResumeVectorStore(Protocol):
    """父子块向量存储的最小接口。"""

    async def index(
        self,
        *,
        resume_id: int,
        user_id: int,
        doc_hash: str,
        chunks: list[ResumeChunk],
    ) -> None: ...

    async def search(
        self,
        *,
        user_id: int,
        query: str,
        limit: int,
        resume_id: int | None = None,
    ) -> list[ResumeChunkMatch]: ...

    async def delete(self, *, resume_id: int, user_id: int) -> None: ...


class ResumeKnowledgeService:
    """协调简历父子分块与 Milvus 索引。"""

    def __init__(
        self,
        *,
        chunking_service: ResumeChunkingService,
        vector_store: ResumeVectorStore,
    ) -> None:
        self._chunking_service = chunking_service
        self._vector_store = vector_store

    async def save(
        self,
        *,
        resume_id: int,
        user_id: int,
        doc_hash: str,
        content: str,
    ) -> None:
        """索引父子块；失败时清理本次 Resume 的向量。"""
        chunks = self._chunking_service.split(resume_id=resume_id, text=content)
        try:
            await self._vector_store.index(
                resume_id=resume_id,
                user_id=user_id,
                doc_hash=doc_hash,
                chunks=chunks,
            )
        except Exception:
            with suppress(Exception):
                await self._vector_store.delete(resume_id=resume_id, user_id=user_id)
            raise

    async def search(
        self,
        *,
        user_id: int,
        query: str,
        limit: int,
        resume_id: int | None = None,
    ) -> list[ResumeChunkMatch]:
        """检索子块，但同时返回父块内容保证上下文和来源完整。"""
        return await self._vector_store.search(
            user_id=user_id,
            resume_id=resume_id,
            query=query,
            limit=limit,
        )
