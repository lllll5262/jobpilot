"""JD 解析、保存与历史查询 Service。"""

from app.core.exceptions import AppException
from app.models.job import Job
from app.repository.job_repository import JobRepository
from app.repository.user_repository import UserRepository
from app.schemas.job import JDParseResult
from app.schemas.persistence import JobRecord
from app.services.jd_parser_service import JDParserService
from app.services.persistence_helpers import require_user


class JobStorageService:
    """管理用户的结构化 JD 与历史记录。"""

    def __init__(
        self,
        parser_service: JDParserService,
        job_repository: JobRepository,
        user_repository: UserRepository,
    ) -> None:
        self._parser_service = parser_service
        self._job_repository = job_repository
        self._user_repository = user_repository

    async def parse_and_save(self, *, user_id: int, jd_text: str) -> JobRecord:
        """解析并保存一个 JD。"""
        await require_user(self._user_repository, user_id)
        parsed_job = await self._parser_service.parse(jd_text)
        record = await self._job_repository.create(
            user_id=user_id,
            raw_text=jd_text,
            parsed_data=parsed_job.model_dump(mode="json"),
        )
        return self._to_record(record, parsed_job)

    async def list_history(self, user_id: int, *, limit: int, offset: int) -> list[JobRecord]:
        """分页获取用户历史 JD。"""
        await require_user(self._user_repository, user_id)
        records = await self._job_repository.list_by_user(
            user_id,
            limit=limit,
            offset=offset,
        )
        return [
            self._to_record(record, JDParseResult.model_validate(record.parsed_data))
            for record in records
        ]

    async def get_many(self, *, user_id: int, job_ids: list[int]) -> list[JobRecord]:
        """按输入顺序读取多个历史 JD，任何一个不存在都拒绝比较。"""
        await require_user(self._user_repository, user_id)
        records = await self._job_repository.get_by_ids(job_ids, user_id=user_id)
        records_by_id = {record.id: record for record in records}
        missing_ids = [job_id for job_id in job_ids if job_id not in records_by_id]
        if missing_ids:
            raise AppException(
                "One or more jobs were not found",
                code=40404,
                status_code=404,
                data={"missing_job_ids": missing_ids},
            )
        return [
            self._to_record(
                records_by_id[job_id],
                JDParseResult.model_validate(records_by_id[job_id].parsed_data),
            )
            for job_id in job_ids
        ]

    @staticmethod
    def _to_record(record: Job, parsed_job: JDParseResult) -> JobRecord:
        """将 ORM 记录转换为 API DTO。"""
        return JobRecord(
            id=record.id,
            user_id=record.user_id,
            raw_text=record.raw_text,
            job=parsed_job,
            created_at=record.created_at,
        )
