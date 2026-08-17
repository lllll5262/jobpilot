"""Supervisor 多 Agent 统一入口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from redis.asyncio import Redis

from app.agents.interview_agent import InterviewAgent
from app.agents.job_agent import JobAgent
from app.agents.resume_agent import ResumeAgent
from app.agents.supervisor import SupervisorAgent
from app.api.agent import get_job_agent
from app.api.dependencies import get_llm_client
from app.api.interview import get_interview_service
from app.api.persistence import (
    get_job_storage_service,
    get_profile_storage_service,
    get_resume_storage_service,
)
from app.core.config import Settings, get_settings
from app.llm.client import OpenAICompatibleClient
from app.memory.checkpointer import RedisCheckpointSaver
from app.memory.connection import get_redis_client
from app.schemas.common import ApiResponse
from app.schemas.supervisor import SupervisorRequest, SupervisorResponse
from app.services.interview_service import InterviewService
from app.services.job_storage_service import JobStorageService
from app.services.profile_storage_service import ProfileStorageService
from app.services.resume_optimization_service import ResumeOptimizationService
from app.services.resume_storage_service import ResumeStorageService

router = APIRouter(prefix="/users/{user_id}/supervisor", tags=["Supervisor Agent"])
UserId = Annotated[int, Path(gt=0)]


def get_resume_agent(
    user_id: UserId,
    model: Annotated[OpenAICompatibleClient, Depends(get_llm_client)],
    resume_service: Annotated[ResumeStorageService, Depends(get_resume_storage_service)],
    profile_service: Annotated[ProfileStorageService, Depends(get_profile_storage_service)],
    job_service: Annotated[JobStorageService, Depends(get_job_storage_service)],
) -> ResumeAgent:
    """组装 Resume Agent 及其四个 Tool 所需 Service。"""
    optimization_service = ResumeOptimizationService(
        llm_client=model,
        resume_service=resume_service,
        profile_service=profile_service,
        job_service=job_service,
    )
    return ResumeAgent(
        user_id=user_id,
        resume_service=resume_service,
        profile_service=profile_service,
        optimization_service=optimization_service,
    )


def get_supervisor_agent(
    user_id: UserId,
    model: Annotated[OpenAICompatibleClient, Depends(get_llm_client)],
    resume_agent: Annotated[ResumeAgent, Depends(get_resume_agent)],
    job_agent: Annotated[JobAgent, Depends(get_job_agent)],
    interview_service: Annotated[InterviewService, Depends(get_interview_service)],
    client: Annotated[Redis, Depends(get_redis_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SupervisorAgent:
    """Supervisor 只持有两个领域 Agent，不注入 Repository 或业务 Service。"""
    return SupervisorAgent(
        model=model,
        resume_agent=resume_agent,
        job_agent=job_agent,
        interview_agent=InterviewAgent(user_id=user_id, service=interview_service),
        user_id=user_id,
        checkpointer=RedisCheckpointSaver(
            client,
            ttl_seconds=settings.checkpoint_ttl_seconds,
        ),
    )


@router.post("", response_model=ApiResponse[SupervisorResponse])
async def dispatch_supervisor_request(
    request: SupervisorRequest,
    supervisor: Annotated[SupervisorAgent, Depends(get_supervisor_agent)],
) -> ApiResponse[SupervisorResponse]:
    """理解用户意图，并把请求委派给 Resume 或 Interview Agent。"""
    return ApiResponse(data=await supervisor.handle(request))
