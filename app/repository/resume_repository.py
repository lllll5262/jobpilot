"""简历 Repository。"""

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.resume import Resume


class ResumeRepository:
    """封装 resumes 表的数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, resume_id: int, *, user_id: int) -> Resume | None:
        """按用户边界获取指定 Resume。"""
        statement = select(Resume).where(
            Resume.id == resume_id,
            Resume.user_id == user_id,
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def get_latest(self, user_id: int) -> Resume | None:
        """获取用户最新 Resume。"""
        statement = (
            select(Resume)
            .where(Resume.user_id == user_id)
            .order_by(desc(Resume.created_at), desc(Resume.id))
            .limit(1)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: int,
        filename: str,
        parsed_data: dict[str, Any],
    ) -> Resume:
        """保存结构化 Resume。"""
        resume = Resume(
            user_id=user_id,
            filename=filename,
            parsed_data=parsed_data,
        )
        self._session.add(resume)
        await self._session.commit()
        await self._session.refresh(resume)
        return resume
