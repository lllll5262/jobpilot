"""候选人画像 Repository。"""

from typing import Any

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import CandidateProfile


class ProfileRepository:
    """封装 candidate_profiles 表及当前版本切换。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_current(self, user_id: int) -> CandidateProfile | None:
        """获取用户当前能力画像。"""
        statement = (
            select(CandidateProfile)
            .where(
                CandidateProfile.user_id == user_id,
                CandidateProfile.is_current.is_(True),
            )
            .order_by(desc(CandidateProfile.created_at), desc(CandidateProfile.id))
            .limit(1)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def create_current(
        self,
        *,
        user_id: int,
        resume_id: int,
        profile_data: dict[str, Any],
    ) -> CandidateProfile:
        """在同一事务内归档旧画像并创建当前画像。"""
        await self._session.execute(
            update(CandidateProfile)
            .where(
                CandidateProfile.user_id == user_id,
                CandidateProfile.is_current.is_(True),
            )
            .values(is_current=False)
        )
        profile = CandidateProfile(
            user_id=user_id,
            resume_id=resume_id,
            profile_data=profile_data,
            is_current=True,
        )
        self._session.add(profile)
        await self._session.commit()
        await self._session.refresh(profile)
        return profile
