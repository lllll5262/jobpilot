"""Milvus 简历父子块混合向量存储。"""

import asyncio
from collections.abc import Mapping
from threading import Lock
from typing import Any

from app.schemas.resume_vector import ResumeChunkMatch
from app.services.resume_chunking_service import ResumeChunk


class MilvusResumeVectorStore:
    """使用 BGE-M3 稠密/稀疏向量和 Milvus WeightedRanker 完成双路排序。"""

    def __init__(
        self,
        *,
        uri: str,
        token: str | None,
        database: str,
        collection: str,
        model_path: str,
        device: str,
        use_fp16: bool,
    ) -> None:
        self._uri = uri
        self._token = token
        self._database = database
        self._collection_name = collection
        self._model_path = model_path
        self._device = device
        self._use_fp16 = use_fp16
        self._client: Any | None = None
        self._embedding: Any | None = None
        self._init_lock = Lock()

    def _ensure_initialized(self) -> None:
        """首次读写时加载本地 BGE-M3 并创建 Milvus Collection。"""
        if self._client is not None and self._embedding is not None:
            return
        with self._init_lock:
            if self._client is not None and self._embedding is not None:
                return

            from milvus_model.hybrid import BGEM3EmbeddingFunction
            from pymilvus import DataType, MilvusClient

            embedding = BGEM3EmbeddingFunction(
                model_name=self._model_path,
                device=self._device,
                use_fp16=self._use_fp16,
            )
            client_options: dict[str, Any] = {
                "uri": self._uri,
                "db_name": self._database,
            }
            if self._token:
                client_options["token"] = self._token
            client = MilvusClient(**client_options)

            if not client.has_collection(self._collection_name):
                schema = MilvusClient.create_schema(
                    auto_id=False,
                    enable_dynamic_field=False,
                )
                schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=160)
                schema.add_field("user_id", DataType.INT64)
                schema.add_field("resume_id", DataType.INT64)
                schema.add_field("doc_hash", DataType.VARCHAR, max_length=64)
                schema.add_field("parent_id", DataType.VARCHAR, max_length=128)
                schema.add_field("parent_index", DataType.INT64)
                schema.add_field("child_index", DataType.INT64)
                schema.add_field("text", DataType.VARCHAR, max_length=8_192)
                schema.add_field("parent_content", DataType.VARCHAR, max_length=16_384)
                schema.add_field(
                    "dense_vector",
                    DataType.FLOAT_VECTOR,
                    dim=embedding.dim["dense"],
                )
                schema.add_field("sparse_vector", DataType.SPARSE_FLOAT_VECTOR)

                indexes = client.prepare_index_params()
                indexes.add_index(
                    field_name="dense_vector",
                    index_name="dense_index",
                    index_type="IVF_FLAT",
                    metric_type="IP",
                    params={"nlist": 128},
                )
                indexes.add_index(
                    field_name="sparse_vector",
                    index_name="sparse_index",
                    index_type="SPARSE_INVERTED_INDEX",
                    metric_type="IP",
                    params={"drop_ratio_build": 0.2},
                )
                client.create_collection(
                    collection_name=self._collection_name,
                    schema=schema,
                    index_params=indexes,
                )
            client.load_collection(self._collection_name)
            self._embedding = embedding
            self._client = client

    @staticmethod
    def _sparse_row(matrix: Any, row: int) -> dict[int, float]:
        """把 BGE-M3 CSR 稀疏矩阵的一行转换为 Milvus 接受的字典。"""
        start = matrix.indptr[row]
        end = matrix.indptr[row + 1]
        return {
            int(index): float(value)
            for index, value in zip(matrix.indices[start:end], matrix.data[start:end], strict=True)
        }

    async def index(
        self,
        *,
        resume_id: int,
        user_id: int,
        doc_hash: str,
        chunks: list[ResumeChunk],
    ) -> None:
        """为所有子块生成双向量并幂等写入 Milvus。"""
        await asyncio.to_thread(self._index_sync, resume_id, user_id, doc_hash, chunks)

    def _index_sync(
        self,
        resume_id: int,
        user_id: int,
        doc_hash: str,
        chunks: list[ResumeChunk],
    ) -> None:
        if not chunks:
            raise ValueError("resume chunks must not be empty")
        self._ensure_initialized()
        embeddings = self._embedding.encode_documents([chunk.text for chunk in chunks])
        entities = [
            {
                "id": chunk.chunk_id,
                "user_id": user_id,
                "resume_id": resume_id,
                "doc_hash": doc_hash,
                "parent_id": chunk.parent_id,
                "parent_index": chunk.parent_index,
                "child_index": chunk.child_index,
                "text": chunk.text,
                "parent_content": chunk.parent_content,
                "dense_vector": embeddings["dense"][index].tolist(),
                "sparse_vector": self._sparse_row(embeddings["sparse"], index),
            }
            for index, chunk in enumerate(chunks)
        ]
        filter_expression = f"user_id == {user_id} and resume_id == {resume_id}"
        self._client.delete(self._collection_name, filter=filter_expression)
        self._client.insert(self._collection_name, entities)

    async def search(
        self,
        *,
        user_id: int,
        query: str,
        limit: int,
        resume_id: int | None = None,
    ) -> list[ResumeChunkMatch]:
        """执行 BGE-M3 稠密/稀疏召回，并由 Milvus 完成加权融合排序。"""
        return await asyncio.to_thread(self._search_sync, user_id, query, limit, resume_id)

    def _search_sync(
        self,
        user_id: int,
        query: str,
        limit: int,
        resume_id: int | None,
    ) -> list[ResumeChunkMatch]:
        from pymilvus import AnnSearchRequest, WeightedRanker

        self._ensure_initialized()
        embeddings = self._embedding.encode_queries([query])
        dense_request = AnnSearchRequest(
            data=[embeddings["dense"][0].tolist()],
            anns_field="dense_vector",
            param={"metric_type": "IP", "params": {"nprobe": 10}},
            limit=limit,
        )
        sparse_request = AnnSearchRequest(
            data=[self._sparse_row(embeddings["sparse"], 0)],
            anns_field="sparse_vector",
            param={"metric_type": "IP"},
            limit=limit,
        )
        conditions = [f"user_id == {user_id}"]
        if resume_id is not None:
            conditions.append(f"resume_id == {resume_id}")
        results = self._client.hybrid_search(
            collection_name=self._collection_name,
            reqs=[dense_request, sparse_request],
            ranker=WeightedRanker(0.7, 0.3),
            limit=limit,
            filter=" and ".join(conditions),
            output_fields=[
                "resume_id",
                "doc_hash",
                "parent_id",
                "text",
                "parent_content",
            ],
        )
        hits = results[0] if results else []
        matches: list[ResumeChunkMatch] = []
        for hit in hits:
            entity = hit.get("entity", {}) if isinstance(hit, Mapping) else hit.entity
            hit_id = hit.get("id") if isinstance(hit, Mapping) else hit.id
            score = hit.get("distance", 0.0) if isinstance(hit, Mapping) else hit.distance
            matches.append(
                ResumeChunkMatch(
                    resume_id=int(entity["resume_id"]),
                    doc_hash=str(entity["doc_hash"]),
                    parent_id=str(entity["parent_id"]),
                    chunk_id=str(hit_id),
                    text=str(entity["text"]),
                    parent_content=str(entity["parent_content"]),
                    score=float(score),
                )
            )
        return matches

    async def delete(self, *, resume_id: int, user_id: int) -> None:
        """删除一次失败写入产生的向量块。"""
        await asyncio.to_thread(self._delete_sync, resume_id, user_id)

    def _delete_sync(self, resume_id: int, user_id: int) -> None:
        self._ensure_initialized()
        self._client.delete(
            self._collection_name,
            filter=f"user_id == {user_id} and resume_id == {resume_id}",
        )

    def close(self) -> None:
        """关闭 Milvus 客户端。"""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._embedding = None
