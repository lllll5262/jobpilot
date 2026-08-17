"""简历父子分块与 Milvus 索引编排。"""

from contextlib import suppress
from typing import Any, Protocol

from app.schemas.resume_vector import ResumeChunkMatch
from app.services.resume_chunking_service import ResumeChunk, ResumeChunkingService


class ResumeDocumentStore(Protocol):
    """完整简历文档存储的最小接口。"""

    async def save(
        self,
        *,
        resume_id: int,
        user_id: int,
        filename: str,
        doc_hash: str,
        content: str,
        structured_data: dict[str, Any],
    ) -> None: ...

    async def get(self, *, resume_id: int, user_id: int) -> dict[str, Any] | None: ...

    async def delete(self, *, resume_id: int, user_id: int) -> None: ...


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
    """协调可选原文存储和 Milvus 检索块，避免业务层依赖具体数据库 SDK。"""

    def __init__(
        self,
        *,
        chunking_service: ResumeChunkingService,
        document_store: ResumeDocumentStore | None,
        vector_store: ResumeVectorStore,
    ) -> None:
        self._chunking_service = chunking_service
        self._document_store = document_store
        self._vector_store = vector_store

    async def save(
        self,
        *,
        resume_id: int,
        user_id: int,
        filename: str,
        doc_hash: str,
        content: str,
        structured_data: dict[str, Any],
    ) -> None:
        """按需保存原文并索引父子块；任一步失败都清理外部写入。"""
        chunks = self._chunking_service.split(resume_id=resume_id, text=content)
        try:
            if self._document_store is not None:
                await self._document_store.save(
                    resume_id=resume_id,
                    user_id=user_id,
                    filename=filename,
                    doc_hash=doc_hash,
                    content=content,
                    structured_data=structured_data,
                )
            await self._vector_store.index(
                resume_id=resume_id,
                user_id=user_id,
                doc_hash=doc_hash,
                chunks=chunks,
            )
        except Exception:
            if self._document_store is not None:
                with suppress(Exception):
                    await self._document_store.delete(resume_id=resume_id, user_id=user_id)
            with suppress(Exception):
                await self._vector_store.delete(resume_id=resume_id, user_id=user_id)
            raise

    async def get_source(self, *, resume_id: int, user_id: int) -> dict[str, Any] | None:
        """未配置文档存储时不提供完整原文。"""
        if self._document_store is None:
            return None
        return await self._document_store.get(resume_id=resume_id, user_id=user_id)

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
