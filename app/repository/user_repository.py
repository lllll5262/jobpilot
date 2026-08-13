"""用户 Repository。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    """封装 users 表的数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: int) -> User | None:
        """按主键获取用户。"""
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """按规范化邮箱获取用户。"""
        statement = select(User).where(User.email == email)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def create(self, *, email: str, name: str | None) -> User:
        """创建用户并提交事务。"""
        user = User(email=email, name=name)
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return user
