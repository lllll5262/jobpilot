"""Resume 解析与持久化 Service。"""

import hashlib
import logging
from contextlib import suppress

from app.core.exceptions import AppException
from app.models.resume import Resume
from app.repository.resume_repository import ResumeRepository
from app.repository.user_repository import UserRepository
from app.schemas.persistence import ResumeRecord
from app.schemas.resume import ResumeParseResult
from app.schemas.resume_vector import ResumeChunkMatch, ResumeSourceRecord
from app.services.persistence_helpers import require_user
from app.services.resume_knowledge_service import ResumeKnowledgeService
from app.services.resume_parser_service import ResumeParserService
from app.storage.resume_object_store import ResumeObjectStore

logger = logging.getLogger(__name__)


class ResumeStorageService:
    """解析 PDF Resume，并保存结构化结果。"""

    def __init__(
        self,
        parser_service: ResumeParserService,
        resume_repository: ResumeRepository,
        user_repository: UserRepository,
        knowledge_service: ResumeKnowledgeService,
        object_store: ResumeObjectStore,
    ) -> None:
        self._parser_service = parser_service
        self._resume_repository = resume_repository
        self._user_repository = user_repository
        self._knowledge_service = knowledge_service
        self._object_store = object_store

    async def parse_and_save(
        self,
        *,
        user_id: int,
        filename: str,
        pdf_content: bytes,
    ) -> ResumeRecord:
        """先确认用户，再解析并保存 Resume。"""
        await require_user(self._user_repository, user_id)
        parsed_document = await self._parser_service.parse_with_source(pdf_content)
        parsed_resume = parsed_document.resume
        doc_hash = hashlib.sha256(pdf_content).hexdigest()
        stored_object = None
        record = None
        try:
            stored_object = await self._object_store.save(
                user_id=user_id,
                filename=filename,
                content=pdf_content,
                content_type="application/pdf",
                doc_hash=doc_hash,
            )
            record = await self._resume_repository.create(
                user_id=user_id,
                filename=filename,
                doc_hash=doc_hash,
                file_size_bytes=stored_object.size_bytes,
                content_type=stored_object.content_type,
                storage_bucket=stored_object.bucket,
                storage_object_key=stored_object.object_key,
                storage_uri=stored_object.storage_uri,
                object_etag=stored_object.etag,
                parsed_data=parsed_resume.model_dump(mode="json"),
            )
            await self._knowledge_service.save(
                resume_id=record.id,
                user_id=user_id,
                doc_hash=doc_hash,
                content=parsed_document.cleaned_text,
            )
        except Exception as exc:
            if record is not None:
                with suppress(Exception):
                    await self._resume_repository.delete(record.id, user_id=user_id)
            if stored_object is not None:
                with suppress(Exception):
                    await self._object_store.delete(
                        bucket=stored_object.bucket,
                        object_key=stored_object.object_key,
                    )
            logger.exception(
                "简历跨存储写入失败 resume_id=%s",
                record.id if record is not None else None,
            )
            raise AppException(
                "Resume storage is unavailable",
                code=50320,
                status_code=503,
            ) from exc
        return self._to_record(record)

    async def search_context(
        self,
        *,
        user_id: int,
        query: str,
        limit: int,
        resume_id: int | None = None,
    ) -> list[ResumeChunkMatch]:
        """通过 Milvus 的稠密/稀疏混合排序检索简历父子块。"""
        await require_user(self._user_repository, user_id)
        return await self._knowledge_service.search(
            user_id=user_id,
            resume_id=resume_id,
            query=query,
            limit=limit,
        )

    async def get_source(self, *, user_id: int, resume_id: int) -> ResumeSourceRecord:
        """从 MySQL 读取对象元数据，并生成 MinIO 短时下载地址。"""
        await require_user(self._user_repository, user_id)
        model = await self._resume_repository.get_by_id(resume_id, user_id=user_id)
        if model is None:
            raise AppException("Resume not found", code=40402, status_code=404)
        if (
            model.doc_hash is None
            or model.file_size_bytes is None
            or model.content_type is None
            or model.storage_bucket is None
            or model.storage_object_key is None
            or model.storage_uri is None
        ):
            raise AppException("Resume source not found", code=40414, status_code=404)
        try:
            download_url = await self._object_store.create_download_url(
                bucket=model.storage_bucket,
                object_key=model.storage_object_key,
            )
        except Exception as exc:
            raise AppException(
                "Resume object storage is unavailable",
                code=50321,
                status_code=503,
            ) from exc
        return ResumeSourceRecord(
            resume_id=resume_id,
            user_id=user_id,
            filename=model.filename,
            doc_hash=model.doc_hash,
            file_size_bytes=model.file_size_bytes,
            content_type=model.content_type,
            storage_uri=model.storage_uri,
            download_url=download_url,
            resume=ResumeParseResult.model_validate(model.parsed_data),
        )

    async def get(self, *, user_id: int, resume_id: int | None = None) -> ResumeRecord:
        """读取指定或最新结构化简历；不返回未保存的 PDF 原文。"""
        await require_user(self._user_repository, user_id)
        record = (
            await self._resume_repository.get_by_id(resume_id, user_id=user_id)
            if resume_id is not None
            else await self._resume_repository.get_latest(user_id)
        )
        if record is None:
            raise AppException("Resume not found", code=40402, status_code=404)
        return self._to_record(record)

    @staticmethod
    def _to_record(record: Resume) -> ResumeRecord:
        """把 ORM Resume 转换为 API DTO。"""
        return ResumeRecord(
            id=record.id,
            user_id=record.user_id,
            filename=record.filename,
            doc_hash=record.doc_hash,
            file_size_bytes=record.file_size_bytes,
            content_type=record.content_type,
            storage_uri=record.storage_uri,
            resume=ResumeParseResult.model_validate(record.parsed_data),
            created_at=record.created_at,
        )
