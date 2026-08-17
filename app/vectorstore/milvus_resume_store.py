"""Milvus 简历父子块混合向量存储。"""

import asyncio
import math
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
        collection_version: str,
        alias: str,
        model_path: str,
        device: str,
        use_fp16: bool,
        embedding_batch_size: int,
    ) -> None:
        self._uri = uri
        self._token = token
        self._database = database
        self._legacy_collection_name = collection
        self._physical_collection_name = f"{collection}_{collection_version}"
        self._collection_name = alias
        self._model_path = model_path
        self._device = device
        self._use_fp16 = use_fp16
        self._embedding_batch_size = embedding_batch_size
        self._client: Any | None = None
        self._embedding: Any | None = None
        self._init_lock = Lock()
        self._embedding_lock = Lock()

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

            aliases = client.list_aliases()
            if self._collection_name not in aliases:
                if client.has_collection(self._physical_collection_name):
                    target_collection = self._physical_collection_name
                elif client.has_collection(self._legacy_collection_name):
                    # 首次升级时让别名指向旧 Collection，避免已有向量不可见。
                    target_collection = self._legacy_collection_name
                else:
                    self._create_collection(
                        client=client,
                        collection_name=self._physical_collection_name,
                        embedding=embedding,
                        milvus_client_type=MilvusClient,
                        data_type=DataType,
                    )
                    target_collection = self._physical_collection_name
                client.create_alias(target_collection, self._collection_name)
            client.load_collection(self._collection_name)
            self._embedding = embedding
            self._client = client

    @staticmethod
    def _create_collection(
        *,
        client: Any,
        collection_name: str,
        embedding: Any,
        milvus_client_type: Any,
        data_type: Any,
    ) -> None:
        """创建一个可由 Alias 原子切换的版本化物理 Collection。"""
        schema = milvus_client_type.create_schema(
            auto_id=False,
            enable_dynamic_field=False,
        )
        schema.add_field("id", data_type.VARCHAR, is_primary=True, max_length=160)
        schema.add_field("user_id", data_type.INT64)
        schema.add_field("resume_id", data_type.INT64)
        schema.add_field("doc_hash", data_type.VARCHAR, max_length=64)
        schema.add_field("parent_id", data_type.VARCHAR, max_length=128)
        schema.add_field("parent_index", data_type.INT64)
        schema.add_field("child_index", data_type.INT64)
        schema.add_field("text", data_type.VARCHAR, max_length=8_192)
        schema.add_field("parent_content", data_type.VARCHAR, max_length=16_384)
        schema.add_field(
            "dense_vector",
            data_type.FLOAT_VECTOR,
            dim=embedding.dim["dense"],
        )
        schema.add_field("sparse_vector", data_type.SPARSE_FLOAT_VECTOR)

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
            collection_name=collection_name,
            schema=schema,
            index_params=indexes,
        )

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
        filter_expression = f"user_id == {user_id} and resume_id == {resume_id}"
        self._client.delete(self._collection_name, filter=filter_expression)
        for start in range(0, len(chunks), self._embedding_batch_size):
            batch = chunks[start : start + self._embedding_batch_size]
            with self._embedding_lock:
                embeddings = self._embedding.encode_documents([chunk.text for chunk in batch])
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
                for index, chunk in enumerate(batch)
            ]
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
        from pymilvus.exceptions import MilvusException

        self._ensure_initialized()
        with self._embedding_lock:
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
        filter_expression = " and ".join(conditions)
        output_fields = [
            "resume_id",
            "doc_hash",
            "parent_id",
            "text",
            "parent_content",
        ]
        try:
            results = self._client.hybrid_search(
                collection_name=self._collection_name,
                reqs=[dense_request, sparse_request],
                ranker=WeightedRanker(0.7, 0.3),
                limit=limit,
                filter=filter_expression,
                output_fields=output_fields,
            )
            hits = results[0] if results else []
        except MilvusException as exc:
            if "unsupported ID type" not in str(exc):
                raise
            hits = self._fallback_weighted_search(
                dense_vector=embeddings["dense"][0].tolist(),
                sparse_vector=self._sparse_row(embeddings["sparse"], 0),
                filter_expression=filter_expression,
                output_fields=output_fields,
                limit=limit,
            )
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

    def _fallback_weighted_search(
        self,
        *,
        dense_vector: list[float],
        sparse_vector: dict[int, float],
        filter_expression: str,
        output_fields: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        """兼容部分 Milvus 3.0 服务端无法融合 VARCHAR 主键的情况。"""
        common_options = {
            "collection_name": self._collection_name,
            "filter": filter_expression,
            "limit": limit,
            "output_fields": output_fields,
        }
        dense_results = self._client.search(
            data=[dense_vector],
            anns_field="dense_vector",
            search_params={"metric_type": "IP", "params": {"nprobe": 10}},
            **common_options,
        )
        sparse_results = self._client.search(
            data=[sparse_vector],
            anns_field="sparse_vector",
            search_params={"metric_type": "IP"},
            **common_options,
        )

        fused: dict[str, dict[str, Any]] = {}
        for results, weight in ((dense_results, 0.7), (sparse_results, 0.3)):
            for hit in results[0] if results else []:
                hit_id = hit.get("id") if isinstance(hit, Mapping) else hit.id
                entity = hit.get("entity", {}) if isinstance(hit, Mapping) else hit.entity
                distance = hit.get("distance", 0.0) if isinstance(hit, Mapping) else hit.distance
                key = str(hit_id)
                item = fused.setdefault(
                    key,
                    {"id": hit_id, "entity": entity, "distance": 0.0},
                )
                item["distance"] += weight * self._normalize_ip_score(float(distance))
        return sorted(fused.values(), key=lambda item: item["distance"], reverse=True)[:limit]

    @staticmethod
    def _normalize_ip_score(score: float) -> float:
        """按 Milvus WeightedRanker 的 arctan 方式把 IP 分数映射到 0 到 1。"""
        return 0.5 + math.atan(score) / math.pi

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
