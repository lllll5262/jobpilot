"""简历异步入库队列的 API 侧适配器。"""

from functools import lru_cache
from typing import Any, Protocol
from uuid import uuid4

from app.schemas.persistence import ResumeIngestionStatus, ResumeRecord
from app.storage.resume_object_store import ResumeObjectMetadata
from app.tasks.celery_app import celery_app

TASK_NAME = "jobpilot.resume.ingest"


class ResumeIngestionQueue(Protocol):
    """API 层需要的最小异步任务接口。"""

    def enqueue(
        self,
        *,
        user_id: int,
        filename: str,
        doc_hash: str,
        stored_object: ResumeObjectMetadata,
    ) -> str: ...

    def get_status(self, *, user_id: int, task_id: str) -> ResumeIngestionStatus: ...


class CeleryResumeIngestionQueue:
    """发布 Celery 任务，并将内部状态转换为稳定 API DTO。"""

    _state_mapping = {
        "PENDING": "pending",
        "RECEIVED": "pending",
        "STARTED": "started",
        "RETRY": "retry",
        "SUCCESS": "succeeded",
        "FAILURE": "failed",
        "REVOKED": "failed",
    }

    def enqueue(
        self,
        *,
        user_id: int,
        filename: str,
        doc_hash: str,
        stored_object: ResumeObjectMetadata,
    ) -> str:
        task_id = f"resume-{user_id}-{uuid4().hex}"
        celery_app.send_task(
            TASK_NAME,
            kwargs={
                "user_id": user_id,
                "filename": filename,
                "doc_hash": doc_hash,
                "stored_object": {
                    "bucket": stored_object.bucket,
                    "object_key": stored_object.object_key,
                    "storage_uri": stored_object.storage_uri,
                    "etag": stored_object.etag,
                    "size_bytes": stored_object.size_bytes,
                    "content_type": stored_object.content_type,
                },
            },
            task_id=task_id,
        )
        return task_id

    def get_status(self, *, user_id: int, task_id: str) -> ResumeIngestionStatus:
        if not task_id.startswith(f"resume-{user_id}-"):
            return ResumeIngestionStatus(task_id=task_id, status="failed")
        result = celery_app.AsyncResult(task_id)
        normalized_state = self._state_mapping.get(result.state, "pending")
        resume = (
            self._read_resume_result(result.result)
            if normalized_state == "succeeded"
            else None
        )
        return ResumeIngestionStatus(
            task_id=task_id,
            status=normalized_state,
            resume=resume,
        )

    @staticmethod
    def _read_resume_result(result: Any) -> ResumeRecord | None:
        if not isinstance(result, dict) or not isinstance(result.get("resume"), dict):
            return None
        return ResumeRecord.model_validate(result["resume"])


@lru_cache
def get_resume_ingestion_queue() -> CeleryResumeIngestionQueue:
    """复用无状态 Celery 队列适配器。"""
    return CeleryResumeIngestionQueue()
