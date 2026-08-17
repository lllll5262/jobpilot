"""可选原文存储与 Milvus 父子块编排测试，不连接真实外部服务。"""

import asyncio
from typing import Any

from app.schemas.resume_vector import ResumeChunkMatch
from app.services.resume_chunking_service import ResumeChunk, ResumeChunkingService
from app.services.resume_knowledge_service import ResumeKnowledgeService


class FakeDocumentStore:
    """记录完整简历写入。"""

    def __init__(self) -> None:
        self.document: dict[str, Any] | None = None
        self.deleted = False

    async def save(self, **values: Any) -> None:
        self.document = values

    async def get(self, *, resume_id: int, user_id: int) -> dict[str, Any] | None:
        if self.document and self.document["resume_id"] == resume_id:
            assert self.document["user_id"] == user_id
            return self.document
        return None

    async def delete(self, *, resume_id: int, user_id: int) -> None:
        del resume_id, user_id
        self.deleted = True


class FakeVectorStore:
    """记录 Milvus 应收到的父子块。"""

    def __init__(self) -> None:
        self.chunks: list[ResumeChunk] = []

    async def index(self, *, chunks: list[ResumeChunk], **_: Any) -> None:
        self.chunks = chunks

    async def search(self, **values: Any) -> list[ResumeChunkMatch]:
        chunk = self.chunks[0]
        return [
            ResumeChunkMatch(
                resume_id=values.get("resume_id") or 10,
                doc_hash="a" * 64,
                parent_id=chunk.parent_id,
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                parent_content=chunk.parent_content,
                score=0.95,
            )
        ]

    async def delete(self, *, resume_id: int, user_id: int) -> None:
        del resume_id, user_id
        self.chunks = []


def test_parent_child_chunks_keep_traceable_parent_content() -> None:
    """每个检索子块都必须能够回溯到较完整的父块。"""
    service = ResumeChunkingService(
        parent_chunk_size=40,
        child_chunk_size=20,
        chunk_overlap=5,
    )

    chunks = service.split(
        resume_id=10,
        text="项目经历\n使用 Redis 和 Lua 实现秒杀库存扣减。\n使用 RabbitMQ 异步创建订单。",
    )

    assert len(chunks) >= 2
    assert chunks[0].chunk_id.startswith("resume_10_parent_0_child_")
    assert chunks[0].text in chunks[0].parent_content
    assert len(chunks[0].parent_content) >= len(chunks[0].text)


def test_knowledge_service_saves_source_and_indexes_chunks() -> None:
    """完整正文进入文档库，只有父子块进入向量库。"""

    async def run() -> None:
        document_store = FakeDocumentStore()
        vector_store = FakeVectorStore()
        service = ResumeKnowledgeService(
            chunking_service=ResumeChunkingService(
                parent_chunk_size=40,
                child_chunk_size=20,
                chunk_overlap=5,
            ),
            document_store=document_store,
            vector_store=vector_store,
        )
        content = "技能：Java、Redis。\n项目：使用 Redis 和 Lua 实现秒杀库存扣减。"

        await service.save(
            resume_id=10,
            user_id=1,
            filename="resume.pdf",
            doc_hash="a" * 64,
            content=content,
            structured_data={"skills": ["Java", "Redis"]},
        )
        matches = await service.search(
            user_id=1,
            resume_id=10,
            query="Redis 高并发",
            limit=5,
        )

        assert document_store.document is not None
        assert document_store.document["content"] == content
        assert vector_store.chunks
        assert matches[0].parent_content

    asyncio.run(run())


def test_knowledge_service_can_index_without_document_store() -> None:
    """关闭 MongoDB 后仍应完成父子分块和向量索引。"""

    async def run() -> None:
        vector_store = FakeVectorStore()
        service = ResumeKnowledgeService(
            chunking_service=ResumeChunkingService(
                parent_chunk_size=40,
                child_chunk_size=20,
                chunk_overlap=5,
            ),
            document_store=None,
            vector_store=vector_store,
        )

        await service.save(
            resume_id=10,
            user_id=1,
            filename="resume.pdf",
            doc_hash="a" * 64,
            content="技能：Java、Redis。项目：使用 Redis 和 Lua 实现库存扣减。",
            structured_data={"skills": ["Java", "Redis"]},
        )

        assert vector_store.chunks
        assert await service.get_source(resume_id=10, user_id=1) is None

    asyncio.run(run())
