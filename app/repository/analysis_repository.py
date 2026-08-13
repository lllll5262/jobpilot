"""岗位分析 Repository。"""

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_analysis import JobAnalysis


class AnalysisRepository:
    """封装 job_analyses 表的数据访问和历史查询。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_user(
        self,
        user_id: int,
        *,
        limit: int,
        offset: int,
    ) -> list[JobAnalysis]:
        """按时间倒序分页获取岗位分析历史。"""
        statement = (
            select(JobAnalysis)
            .where(JobAnalysis.user_id == user_id)
            .order_by(desc(JobAnalysis.created_at), desc(JobAnalysis.id))
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(statement)).scalars().all())

    async def create(
        self,
        *,
        user_id: int,
        resume_id: int,
        profile_id: int,
        job_id: int,
        match_score: int,
        recommendation: str,
        result_data: dict[str, Any],
    ) -> JobAnalysis:
        """保存一次完整岗位匹配结果。"""
        analysis = JobAnalysis(
            user_id=user_id,
            resume_id=resume_id,
            profile_id=profile_id,
            job_id=job_id,
            match_score=match_score,
            recommendation=recommendation,
            result_data=result_data,
        )
        self._session.add(analysis)
        await self._session.commit()
        await self._session.refresh(analysis)
        return analysis
