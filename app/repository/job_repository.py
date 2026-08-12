"""岗位 Repository。"""

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job


class JobRepository:
    """封装 jobs 表的数据访问和历史查询。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, job_id: int, *, user_id: int) -> Job | None:
        """按用户边界获取指定 JD。"""
        statement = select(Job).where(Job.id == job_id, Job.user_id == user_id)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: int,
        *,
        limit: int,
        offset: int,
    ) -> list[Job]:
        """按时间倒序分页获取历史 JD。"""
        statement = (
            select(Job)
            .where(Job.user_id == user_id)
            .order_by(desc(Job.created_at), desc(Job.id))
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(statement)).scalars().all())

    async def create(
        self,
        *,
        user_id: int,
        raw_text: str,
        parsed_data: dict[str, Any],
    ) -> Job:
        """保存原始 JD 和结构化解析结果。"""
        job = Job(
            user_id=user_id,
            raw_text=raw_text,
            parsed_data=parsed_data,
        )
        self._session.add(job)
        await self._session.commit()
        await self._session.refresh(job)
        return job
