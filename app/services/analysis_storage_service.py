"""岗位分析执行、保存与历史查询 Service。"""

from app.core.exceptions import AppException
from app.models.job_analysis import JobAnalysis
from app.repository.analysis_repository import AnalysisRepository
from app.repository.job_repository import JobRepository
from app.repository.profile_repository import ProfileRepository
from app.repository.resume_repository import ResumeRepository
from app.repository.user_repository import UserRepository
from app.schemas.job import JDParseResult
from app.schemas.match import MatchResult
from app.schemas.persistence import AnalysisDraft, AnalysisRecord
from app.schemas.profile import CandidateProfile
from app.schemas.resume import ResumeParseResult
from app.services.match_service import MatchService
from app.services.persistence_helpers import require_user


class AnalysisStorageService:
    """使用当前 Profile 执行岗位匹配，并保存完整结果。"""

    def __init__(
        self,
        match_service: MatchService,
        analysis_repository: AnalysisRepository,
        job_repository: JobRepository,
        profile_repository: ProfileRepository,
        resume_repository: ResumeRepository,
        user_repository: UserRepository,
    ) -> None:
        self._match_service = match_service
        self._analysis_repository = analysis_repository
        self._job_repository = job_repository
        self._profile_repository = profile_repository
        self._resume_repository = resume_repository
        self._user_repository = user_repository

    async def analyze_and_save(self, *, user_id: int, job_id: int) -> AnalysisRecord:
        """兼容阶段 5 接口：依次计算并保存岗位分析。"""
        draft = await self.calculate(user_id=user_id, job_id=job_id)
        return await self.save(draft)

    async def calculate(self, *, user_id: int, job_id: int) -> AnalysisDraft:
        """加载当前 Profile 和 Resume 并计算匹配，但不写数据库。"""
        return (await self.calculate_many(user_id=user_id, job_ids=[job_id]))[0]

    async def calculate_many(
        self,
        *,
        user_id: int,
        job_ids: list[int],
    ) -> list[AnalysisDraft]:
        """只加载一次候选人上下文，依次计算多个历史岗位。"""
        await require_user(self._user_repository, user_id)
        job_records = await self._job_repository.get_by_ids(job_ids, user_id=user_id)
        jobs_by_id = {record.id: record for record in job_records}
        missing_ids = [job_id for job_id in job_ids if job_id not in jobs_by_id]
        if missing_ids:
            raise AppException(
                "One or more jobs were not found",
                code=40404,
                status_code=404,
                data={"missing_job_ids": missing_ids},
            )
        profile_record = await self._profile_repository.get_current(user_id)
        if profile_record is None:
            raise AppException("Current profile not found", code=40403, status_code=404)
        resume_record = await self._resume_repository.get_by_id(
            profile_record.resume_id,
            user_id=user_id,
        )
        if resume_record is None:
            raise AppException("Resume not found", code=40402, status_code=404)

        resume = ResumeParseResult.model_validate(resume_record.parsed_data)
        profile = CandidateProfile.model_validate(profile_record.profile_data)
        drafts: list[AnalysisDraft] = []
        for job_id in job_ids:
            job_record = jobs_by_id[job_id]
            result = await self._match_service.match(
                resume=resume,
                profile=profile,
                job=JDParseResult.model_validate(job_record.parsed_data),
            )
            drafts.append(
                AnalysisDraft(
                    user_id=user_id,
                    resume_id=resume_record.id,
                    profile_id=profile_record.id,
                    job_id=job_record.id,
                    result=result,
                )
            )
        return drafts

    async def save(self, draft: AnalysisDraft) -> AnalysisRecord:
        """保存已经完成计算且通过 Pydantic 校验的分析草稿。"""
        record = await self._analysis_repository.create(
            user_id=draft.user_id,
            resume_id=draft.resume_id,
            profile_id=draft.profile_id,
            job_id=draft.job_id,
            match_score=draft.result.match_score,
            recommendation=draft.result.recommendation.value,
            result_data=draft.result.model_dump(mode="json"),
        )
        return self._to_record(record, draft.result)

    async def list_history(
        self,
        user_id: int,
        *,
        limit: int,
        offset: int,
    ) -> list[AnalysisRecord]:
        """分页获取用户历史岗位分析。"""
        await require_user(self._user_repository, user_id)
        records = await self._analysis_repository.list_by_user(
            user_id,
            limit=limit,
            offset=offset,
        )
        return [
            self._to_record(record, MatchResult.model_validate(record.result_data))
            for record in records
        ]

    @staticmethod
    def _to_record(record: JobAnalysis, result: MatchResult) -> AnalysisRecord:
        """将 ORM 记录转换为 API DTO。"""
        return AnalysisRecord(
            id=record.id,
            user_id=record.user_id,
            resume_id=record.resume_id,
            profile_id=record.profile_id,
            job_id=record.job_id,
            result=result,
            created_at=record.created_at,
        )
