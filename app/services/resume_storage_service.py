"""Resume 解析与持久化 Service。"""

from app.core.exceptions import AppException
from app.models.resume import Resume
from app.repository.resume_repository import ResumeRepository
from app.repository.user_repository import UserRepository
from app.schemas.persistence import ResumeRecord
from app.schemas.resume import ResumeParseResult
from app.services.persistence_helpers import require_user
from app.services.resume_parser_service import ResumeParserService


class ResumeStorageService:
    """解析 PDF Resume，并保存结构化结果。"""

    def __init__(
        self,
        parser_service: ResumeParserService,
        resume_repository: ResumeRepository,
        user_repository: UserRepository,
    ) -> None:
        self._parser_service = parser_service
        self._resume_repository = resume_repository
        self._user_repository = user_repository

    async def parse_and_save(
        self,
        *,
        user_id: int,
        filename: str,
        pdf_content: bytes,
    ) -> ResumeRecord:
        """先确认用户，再解析并保存 Resume。"""
        await require_user(self._user_repository, user_id)
        parsed_resume = await self._parser_service.parse(pdf_content)
        record = await self._resume_repository.create(
            user_id=user_id,
            filename=filename,
            parsed_data=parsed_resume.model_dump(mode="json"),
        )
        return ResumeRecord(
            id=record.id,
            user_id=record.user_id,
            filename=record.filename,
            resume=parsed_resume,
            created_at=record.created_at,
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
