"""Candidate Profile 构建与持久化 Service。"""

from app.core.exceptions import AppException
from app.models.profile import CandidateProfile as CandidateProfileModel
from app.repository.profile_repository import ProfileRepository
from app.repository.resume_repository import ResumeRepository
from app.repository.user_repository import UserRepository
from app.schemas.persistence import ProfileRecord
from app.schemas.profile import CandidateProfile
from app.schemas.resume import ResumeParseResult
from app.services.persistence_helpers import require_user
from app.services.profile_service import CandidateProfileService


class ProfileStorageService:
    """从已保存 Resume 构建新 Profile，并切换当前版本。"""

    def __init__(
        self,
        builder_service: CandidateProfileService,
        profile_repository: ProfileRepository,
        resume_repository: ResumeRepository,
        user_repository: UserRepository,
    ) -> None:
        self._builder_service = builder_service
        self._profile_repository = profile_repository
        self._resume_repository = resume_repository
        self._user_repository = user_repository

    async def build_and_save(self, *, user_id: int, resume_id: int) -> ProfileRecord:
        """构建 Profile 并把旧的当前版本归档。"""
        await require_user(self._user_repository, user_id)
        resume_record = await self._resume_repository.get_by_id(resume_id, user_id=user_id)
        if resume_record is None:
            raise AppException("Resume not found", code=40402, status_code=404)

        resume = ResumeParseResult.model_validate(resume_record.parsed_data)
        profile = await self._builder_service.build(resume)
        record = await self._profile_repository.create_current(
            user_id=user_id,
            resume_id=resume_id,
            profile_data=profile.model_dump(mode="json"),
        )
        return self._to_record(record, profile)

    async def get_current(self, user_id: int) -> ProfileRecord:
        """获取当前 Profile。"""
        await require_user(self._user_repository, user_id)
        record = await self._profile_repository.get_current(user_id)
        if record is None:
            raise AppException("Current profile not found", code=40403, status_code=404)
        profile = CandidateProfile.model_validate(record.profile_data)
        return self._to_record(record, profile)

    @staticmethod
    def _to_record(
        record: CandidateProfileModel,
        profile: CandidateProfile,
    ) -> ProfileRecord:
        """将 ORM 记录转换为 API DTO。"""
        return ProfileRecord(
            id=record.id,
            user_id=record.user_id,
            resume_id=record.resume_id,
            profile=profile,
            is_current=record.is_current,
            created_at=record.created_at,
        )
