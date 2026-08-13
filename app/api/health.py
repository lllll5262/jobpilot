"""健康检查接口。"""

from fastapi import APIRouter

from app.schemas.common import ApiResponse
from app.schemas.health import HealthData

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=ApiResponse[HealthData])
async def health_check() -> ApiResponse[HealthData]:
    """返回服务存活状态，供监控系统和容器探针调用。"""
    return ApiResponse(data=HealthData(status="ok"))
