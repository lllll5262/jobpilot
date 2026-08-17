"""MongoDB 完整简历文档存储。"""

import asyncio
from datetime import UTC, datetime
from threading import Lock
from typing import Any


class MongoResumeDocumentStore:
    """保存完整正文和结构化结果，Milvus 命中后可按 resume_id 回溯原文。"""

    def __init__(self, *, url: str, database: str, collection: str) -> None:
        self._url = url
        self._database = database
        self._collection_name = collection
        self._client: Any | None = None
        self._collection: Any | None = None
        self._init_lock = Lock()

    def _get_collection(self) -> Any:
        """延迟连接，避免应用启动时因 MongoDB 暂不可用而整体失败。"""
        if self._collection is not None:
            return self._collection
        with self._init_lock:
            if self._collection is None:
                from pymongo import ASCENDING, MongoClient

                self._client = MongoClient(self._url, serverSelectionTimeoutMS=5_000)
                self._client.admin.command("ping")
                collection = self._client[self._database][self._collection_name]
                collection.create_index(
                    [("user_id", ASCENDING), ("resume_id", ASCENDING)],
                    unique=True,
                    name="uq_resume_user_id",
                )
                collection.create_index(
                    [("user_id", ASCENDING), ("doc_hash", ASCENDING)],
                    name="ix_resume_user_hash",
                )
                self._collection = collection
        return self._collection

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
        """幂等保存完整简历；同一 resume_id 重试时覆盖旧的未完成写入。"""
        await asyncio.to_thread(
            self._save_sync,
            resume_id,
            user_id,
            filename,
            doc_hash,
            content,
            structured_data,
        )

    def _save_sync(
        self,
        resume_id: int,
        user_id: int,
        filename: str,
        doc_hash: str,
        content: str,
        structured_data: dict[str, Any],
    ) -> None:
        collection = self._get_collection()
        collection.replace_one(
            {"user_id": user_id, "resume_id": resume_id},
            {
                "resume_id": resume_id,
                "user_id": user_id,
                "filename": filename,
                "doc_hash": doc_hash,
                "content": content,
                "structured_data": structured_data,
                "updated_at": datetime.now(UTC),
            },
            upsert=True,
        )

    async def get(self, *, resume_id: int, user_id: int) -> dict[str, Any] | None:
        """按用户边界读取完整简历文档。"""
        return await asyncio.to_thread(
            self._get_collection().find_one,
            {"user_id": user_id, "resume_id": resume_id},
            {"_id": 0},
        )

    async def delete(self, *, resume_id: int, user_id: int) -> None:
        """补偿失败的跨存储写入。"""
        await asyncio.to_thread(
            self._get_collection().delete_one,
            {"user_id": user_id, "resume_id": resume_id},
        )

    def close(self) -> None:
        """关闭 MongoDB 客户端。"""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._collection = None
