"""健康检查响应模型。"""

from typing import Literal

from pydantic import BaseModel


class HealthData(BaseModel):
    """健康检查业务数据。"""

    status: Literal["ok"] = "ok"
