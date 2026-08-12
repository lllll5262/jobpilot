"""Job Agent HTTP 接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.agents.job_agent import JobAgent
from app.api.dependencies import get_llm_client
from app.api.persistence import (
    get_analysis_storage_service,
    get_job_storage_service,
    get_profile_storage_service,
)
from app.llm.client import OpenAICompatibleClient
from app.schemas.agent import JobAgentRequest, JobAgentResponse
from app.schemas.common import ApiResponse
from app.services.analysis_storage_service import AnalysisStorageService
from app.services.job_storage_service import JobStorageService
from app.services.profile_storage_service import ProfileStorageService

router = APIRouter(tags=["Job Agent"])


def get_job_agent(
    user_id: Annotated[int, Path(gt=0)],
    model: Annotated[OpenAICompatibleClient, Depends(get_llm_client)],
    profile_service: Annotated[ProfileStorageService, Depends(get_profile_storage_service)],
    job_service: Annotated[JobStorageService, Depends(get_job_storage_service)],
    analysis_service: Annotated[AnalysisStorageService, Depends(get_analysis_storage_service)],
) -> JobAgent:
    """按请求组装单 Agent；业务依赖继续由现有 Service 提供。"""
    return JobAgent(
        model=model,
        user_id=user_id,
        profile_service=profile_service,
        job_service=job_service,
        analysis_service=analysis_service,
    )


@router.post(
    "/users/{user_id}/agents/job/analyze",
    response_model=ApiResponse[JobAgentResponse],
)
async def analyze_job_with_agent(
    request: JobAgentRequest,
    agent: Annotated[JobAgent, Depends(get_job_agent)],
) -> ApiResponse[JobAgentResponse]:
    """让 Job Agent 调用工具完成一次岗位分析并保存结果。"""
    return ApiResponse(data=await agent.analyze(request))
