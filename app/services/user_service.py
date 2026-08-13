"""用户持久化 Service。"""

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AppException
from app.repository.user_repository import UserRepository
from app.schemas.persistence import UserCreateRequest, UserRecord


class UserService:
    """管理阶段 5 的最小用户记录，不涉及认证。"""

    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    async def create(self, request: UserCreateRequest) -> UserRecord:
        """创建用户，并对重复邮箱返回冲突错误。"""
        if await self._repository.get_by_email(request.email) is not None:
            raise AppException("Email already exists", code=40901, status_code=409)
        try:
            user = await self._repository.create(email=request.email, name=request.name)
        except IntegrityError as exc:
            raise AppException("Email already exists", code=40901, status_code=409) from exc
        return UserRecord(
            id=user.id,
            email=user.email,
            name=user.name,
            created_at=user.created_at,
        )
