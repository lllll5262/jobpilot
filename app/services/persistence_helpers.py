"""持久化 Service 的共享边界检查。"""

from app.core.exceptions import AppException
from app.models.user import User
from app.repository.user_repository import UserRepository


async def require_user(repository: UserRepository, user_id: int) -> User:
    """确保用户存在，否则返回统一 404。"""
    user = await repository.get_by_id(user_id)
    if user is None:
        raise AppException("User not found", code=40401, status_code=404)
    return user
