"""Resume 解析与持久化 Service。"""

from app.repository.resume_repository import ResumeRepository
from app.repository.user_repository import UserRepository
from app.schemas.persistence import ResumeRecord
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
