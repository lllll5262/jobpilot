"""Resume 解析与持久化 Service。"""

import hashlib
import logging
from contextlib import suppress
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

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
from app.storage.resume_object_store import ResumeObjectMetadata, ResumeObjectStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResumeIngestionPreparation:
    """异步入库提交前的去重结果或 MinIO 暂存对象。"""

    doc_hash: str
    duplicate: ResumeRecord | None = None
    stored_object: ResumeObjectMetadata | None = None


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
        doc_hash = hashlib.sha256(pdf_content).hexdigest()
        duplicate = await self._resume_repository.get_by_hash(
            user_id=user_id,
            doc_hash=doc_hash,
        )
        if duplicate is not None:
            return self._to_record(duplicate, duplicate=True)

        parsed_document = await self._parser_service.parse_with_source(pdf_content)
        stored_object = None
        try:
            stored_object = await self._object_store.save(
                user_id=user_id,
                filename=filename,
                content=pdf_content,
                content_type="application/pdf",
                doc_hash=doc_hash,
            )
            return await self._persist_parsed_resume(
                user_id=user_id,
                filename=filename,
                doc_hash=doc_hash,
                stored_object=stored_object,
                parsed_resume=parsed_document.resume,
                cleaned_text=parsed_document.cleaned_text,
            )
        except Exception as exc:
            if stored_object is not None:
                with suppress(Exception):
                    await self._object_store.delete(
                        bucket=stored_object.bucket,
                        object_key=stored_object.object_key,
                    )
            return await self._handle_storage_failure(
                exc=exc,
                user_id=user_id,
                doc_hash=doc_hash,
                record=None,
            )

    async def prepare_async_ingestion(
        self,
        *,
        user_id: int,
        filename: str,
        pdf_content: bytes,
    ) -> ResumeIngestionPreparation:
        """去重后将 PDF 暂存到 MinIO；Celery 消息仅需携带对象元数据。"""
        await require_user(self._user_repository, user_id)
        doc_hash = hashlib.sha256(pdf_content).hexdigest()
        duplicate = await self._resume_repository.get_by_hash(
            user_id=user_id,
            doc_hash=doc_hash,
        )
        if duplicate is not None:
            return ResumeIngestionPreparation(
                doc_hash=doc_hash,
                duplicate=self._to_record(duplicate, duplicate=True),
            )
        stored_object = await self._object_store.save(
            user_id=user_id,
            filename=filename,
            content=pdf_content,
            content_type="application/pdf",
            doc_hash=doc_hash,
        )
        return ResumeIngestionPreparation(
            doc_hash=doc_hash,
            stored_object=stored_object,
        )

    async def parse_staged_and_save(
        self,
        *,
        user_id: int,
        filename: str,
        pdf_content: bytes,
        doc_hash: str,
        stored_object: ResumeObjectMetadata,
    ) -> ResumeRecord:
        """Celery Worker 复用已暂存对象，完成解析、MySQL 写入和 Milvus 索引。"""
        await require_user(self._user_repository, user_id)
        if hashlib.sha256(pdf_content).hexdigest() != doc_hash:
            await self.discard_staged(stored_object)
            raise AppException("Resume content checksum mismatch", code=40014, status_code=400)

        duplicate = await self._resume_repository.get_by_hash(
            user_id=user_id,
            doc_hash=doc_hash,
        )
        if duplicate is not None:
            await self.discard_staged(stored_object)
            return self._to_record(duplicate, duplicate=True)

        try:
            parsed_document = await self._parser_service.parse_with_source(pdf_content)
            return await self._persist_parsed_resume(
                user_id=user_id,
                filename=filename,
                doc_hash=doc_hash,
                stored_object=stored_object,
                parsed_resume=parsed_document.resume,
                cleaned_text=parsed_document.cleaned_text,
            )
        except Exception as exc:
            with suppress(Exception):
                await self.discard_staged(stored_object)
            return await self._handle_storage_failure(
                exc=exc,
                user_id=user_id,
                doc_hash=doc_hash,
                record=None,
            )

    async def discard_staged(self, stored_object: ResumeObjectMetadata) -> None:
        """任务发布失败或重复命中时删除尚未成为正式简历的 MinIO 对象。"""
        await self._object_store.delete(
            bucket=stored_object.bucket,
            object_key=stored_object.object_key,
        )

    async def _persist_parsed_resume(
        self,
        *,
        user_id: int,
        filename: str,
        doc_hash: str,
        stored_object: ResumeObjectMetadata,
        parsed_resume: ResumeParseResult,
        cleaned_text: str,
    ) -> ResumeRecord:
        """把同一份解析结果依次写入 MySQL 和 Milvus。"""
        record = None
        try:
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
                content=cleaned_text,
            )
        except Exception as exc:
            if record is not None:
                with suppress(Exception):
                    await self._resume_repository.delete(record.id, user_id=user_id)
            with suppress(Exception):
                await self.discard_staged(stored_object)
            return await self._handle_storage_failure(
                exc=exc,
                user_id=user_id,
                doc_hash=doc_hash,
                record=record,
            )
        return self._to_record(record)

    async def _handle_storage_failure(
        self,
        *,
        exc: Exception,
        user_id: int,
        doc_hash: str,
        record: Resume | None,
    ) -> ResumeRecord:
        """处理并发去重竞争，其他异常统一转为稳定的服务错误。"""
        if isinstance(exc, IntegrityError):
            duplicate = await self._resume_repository.get_by_hash(
                user_id=user_id,
                doc_hash=doc_hash,
            )
            if duplicate is not None:
                return self._to_record(duplicate, duplicate=True)
        logger.exception(
            "简历跨存储写入失败 resume_id=%s",
            record.id if record is not None else None,
        )
        raise AppException(
            "Resume storage is unavailable",
            code=50320,
            status_code=503,
        ) from exc

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
    def _to_record(record: Resume, *, duplicate: bool = False) -> ResumeRecord:
        """把 ORM Resume 转换为 API DTO。"""
        return ResumeRecord(
            id=record.id,
            user_id=record.user_id,
            filename=record.filename,
            duplicate=duplicate,
            doc_hash=record.doc_hash,
            file_size_bytes=record.file_size_bytes,
            content_type=record.content_type,
            storage_uri=record.storage_uri,
            resume=ResumeParseResult.model_validate(record.parsed_data),
            created_at=record.created_at,
        )
