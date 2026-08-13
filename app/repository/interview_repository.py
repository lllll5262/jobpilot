"""自适应面试 Repository。"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview import InterviewSession


class InterviewRepository:
    """封装面试会话创建、加锁读取和进度更新。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: int,
        resume_id: int,
        profile_id: int,
        job_id: int,
        rounds_data: list[dict[str, Any]],
    ) -> InterviewSession:
        """保存第一道简历问题并创建面试会话。"""
        record = InterviewSession(
            user_id=user_id,
            resume_id=resume_id,
            profile_id=profile_id,
            job_id=job_id,
            rounds_data=rounds_data,
            weak_points=[],
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def get_by_id(
        self,
        session_id: int,
        *,
        user_id: int,
        for_update: bool = False,
    ) -> InterviewSession | None:
        """按用户边界读取会话；提交答案时使用行锁防止重复作答。"""
        statement = select(InterviewSession).where(
            InterviewSession.id == session_id,
            InterviewSession.user_id == user_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def update_progress(
        self,
        record: InterviewSession,
        *,
        rounds_data: list[dict[str, Any]],
        weak_points: list[str],
    ) -> InterviewSession:
        """替换 JSON 字段并提交本轮结果。"""
        record.rounds_data = rounds_data
        record.weak_points = weak_points
        await self._session.commit()
        await self._session.refresh(record)
        return record
