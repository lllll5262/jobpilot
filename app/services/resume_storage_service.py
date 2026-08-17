"""Resume 解析与持久化 Service。"""

import hashlib
import logging

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

logger = logging.getLogger(__name__)


class ResumeStorageService:
    """解析 PDF Resume，并保存结构化结果。"""

    def __init__(
        self,
        parser_service: ResumeParserService,
        resume_repository: ResumeRepository,
        user_repository: UserRepository,
        knowledge_service: ResumeKnowledgeService,
    ) -> None:
        self._parser_service = parser_service
        self._resume_repository = resume_repository
        self._user_repository = user_repository
        self._knowledge_service = knowledge_service

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
        record = await self._resume_repository.create(
            user_id=user_id,
            filename=filename,
            parsed_data=parsed_resume.model_dump(mode="json"),
        )
        try:
            await self._knowledge_service.save(
                resume_id=record.id,
                user_id=user_id,
                filename=filename,
                doc_hash=hashlib.sha256(pdf_content).hexdigest(),
                content=parsed_document.cleaned_text,
                structured_data=parsed_resume.model_dump(mode="json"),
            )
        except Exception as exc:
            # MySQL 记录只用于维持现有 Profile/Interview 外键；外部存储失败时同步回滚。
            await self._resume_repository.delete(record.id, user_id=user_id)
            logger.exception("简历写入 MongoDB/Milvus 失败 resume_id=%s", record.id)
            raise AppException(
                "Resume knowledge storage is unavailable",
                code=50320,
                status_code=503,
            ) from exc
        return ResumeRecord(
            id=record.id,
            user_id=record.user_id,
            filename=record.filename,
            resume=parsed_resume,
            created_at=record.created_at,
        )

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
        """从 MongoDB 读取完整原文和结构化结果，用于核对模型回答来源。"""
        await require_user(self._user_repository, user_id)
        document = await self._knowledge_service.get_source(
            resume_id=resume_id,
            user_id=user_id,
        )
        if document is None:
            raise AppException("Resume source not found", code=40414, status_code=404)
        return ResumeSourceRecord(
            resume_id=resume_id,
            user_id=user_id,
            filename=document["filename"],
            doc_hash=document["doc_hash"],
            content=document["content"],
            resume=ResumeParseResult.model_validate(document["structured_data"]),
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
            resume=ResumeParseResult.model_validate(record.parsed_data),
            created_at=record.created_at,
        )
