"""MinIO 结构化简历内容读写服务。"""

import json

from app.core.exceptions import AppException
from app.models.resume import Resume
from app.schemas.resume import ResumeParseResult
from app.storage.resume_object_store import ResumeObjectMetadata, ResumeObjectStore


class ResumeContentService:
    """将结构化 Resume 保存在 MinIO，MySQL 仅提供对象定位元数据。"""

    def __init__(self, object_store: ResumeObjectStore) -> None:
        self._object_store = object_store

    async def save(
        self,
        *,
        stored_object: ResumeObjectMetadata,
        resume: ResumeParseResult,
    ) -> None:
        payload = json.dumps(
            resume.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        await self._object_store.save_parsed_resume(
            bucket=stored_object.bucket,
            pdf_object_key=stored_object.object_key,
            content=payload,
        )

    async def load(self, record: Resume) -> ResumeParseResult:
        if record.storage_bucket is None or record.storage_object_key is None:
            raise AppException("Resume content not found", code=40415, status_code=404)
        try:
            payload = await self._object_store.read_parsed_resume(
                bucket=record.storage_bucket,
                pdf_object_key=record.storage_object_key,
            )
            return ResumeParseResult.model_validate_json(payload)
        except AppException:
            raise
        except Exception as exc:
            raise AppException(
                "Resume content storage is unavailable",
                code=50323,
                status_code=503,
            ) from exc
