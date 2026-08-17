"""Milvus 批量向量化与版本别名测试。"""

from typing import Any

from scipy.sparse import csr_array

from app.services.resume_chunking_service import ResumeChunk
from app.vectorstore.milvus_resume_store import MilvusResumeVectorStore


class FakeEmbedding:
    """记录每次 BGE-M3 批处理大小。"""

    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def encode_documents(self, texts: list[str]) -> dict[str, Any]:
        self.batch_sizes.append(len(texts))
        return {
            "dense": FakeDenseRows(len(texts)),
            "sparse": csr_array([[1.0, 0.0] for _ in texts]),
        }


class FakeDenseRow:
    def tolist(self) -> list[float]:
        return [1.0, 0.0]


class FakeDenseRows:
    def __init__(self, size: int) -> None:
        self._rows = [FakeDenseRow() for _ in range(size)]

    def __getitem__(self, index: int) -> FakeDenseRow:
        return self._rows[index]


class FakeMilvusClient:
    """只实现批量索引所需的 MilvusClient 方法。"""

    def __init__(self) -> None:
        self.deleted_from: str | None = None
        self.inserted: list[tuple[str, list[dict[str, Any]]]] = []

    def delete(self, collection_name: str, *, filter: str) -> None:
        del filter
        self.deleted_from = collection_name

    def insert(self, collection_name: str, entities: list[dict[str, Any]]) -> None:
        self.inserted.append((collection_name, entities))


def test_milvus_embeddings_and_inserts_are_batched_through_alias() -> None:
    """大量子块必须按配置批量编码、批量写入，并始终使用逻辑 Alias。"""
    store = MilvusResumeVectorStore(
        uri="http://milvus:19530",
        token=None,
        database="default",
        collection="jobpilot_resume_chunks",
        collection_version="v1",
        alias="jobpilot_resume_chunks_current",
        model_path="models/bge-m3",
        device="cpu",
        use_fp16=False,
        embedding_batch_size=2,
    )
    client = FakeMilvusClient()
    embedding = FakeEmbedding()
    store._client = client
    store._embedding = embedding
    chunks = [
        ResumeChunk(
            chunk_id=f"chunk-{index}",
            parent_id="parent-0",
            parent_index=0,
            child_index=index,
            text=f"text-{index}",
            parent_content="parent",
        )
        for index in range(5)
    ]

    store._index_sync(10, 1, "a" * 64, chunks)

    assert embedding.batch_sizes == [2, 2, 1]
    assert client.deleted_from == "jobpilot_resume_chunks_current"
    assert [len(entities) for _, entities in client.inserted] == [2, 2, 1]
    assert {name for name, _ in client.inserted} == {"jobpilot_resume_chunks_current"}
