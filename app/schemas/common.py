"""通用响应模型。"""

from typing import Generic, TypeVar

from pydantic import BaseModel

DataT = TypeVar("DataT")


class ApiResponse(BaseModel, Generic[DataT]):
    """所有 HTTP 接口共用的外层响应结构。"""

    code: int = 0
    message: str = "success"
    data: DataT | None = None
