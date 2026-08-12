"""Job Agent HTTP 接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from redis.asyncio import Redis

from app.agents.job_agent import JobAgent
from app.api.dependencies import get_llm_client
from app.api.persistence import (
    get_analysis_storage_service,
    get_job_storage_service,
    get_profile_storage_service,
)
from app.core.config import Settings, get_settings
from app.llm.client import OpenAICompatibleClient
from app.memory.checkpointer import RedisCheckpointSaver
from app.memory.connection import get_redis_client
from app.memory.conversation_memory import ConversationMemory
from app.memory.session_store import AnalysisContextCache, SessionStore
from app.schemas.agent import (
    JobAgentComparisonResponse,
    JobAgentRequest,
    JobAgentResponse,
    JobAgentSessionRequest,
    JobAgentSessionResponse,
    JobAgentSessionState,
)
from app.schemas.common import ApiResponse
from app.schemas.comparison import JobComparisonRequest
from app.services.analysis_storage_service import AnalysisStorageService
from app.services.gap_analysis_service import GapAnalysisService
from app.services.job_compare_service import JobCompareService
from app.services.job_storage_service import JobStorageService
from app.services.profile_storage_service import ProfileStorageService
from app.services.session_service import SessionService

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


def get_session_job_agent(
    user_id: Annotated[int, Path(gt=0)],
    model: Annotated[OpenAICompatibleClient, Depends(get_llm_client)],
    profile_service: Annotated[ProfileStorageService, Depends(get_profile_storage_service)],
    job_service: Annotated[JobStorageService, Depends(get_job_storage_service)],
    analysis_service: Annotated[AnalysisStorageService, Depends(get_analysis_storage_service)],
    client: Annotated[Redis, Depends(get_redis_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JobAgent:
    """为多轮会话组装带 Redis Checkpointer 的 Job Agent。"""
    return JobAgent(
        model=model,
        user_id=user_id,
        profile_service=profile_service,
        job_service=job_service,
        analysis_service=analysis_service,
        checkpointer=RedisCheckpointSaver(
            client,
            ttl_seconds=settings.checkpoint_ttl_seconds,
        ),
    )


def get_gap_analysis_service(
    model: Annotated[OpenAICompatibleClient, Depends(get_llm_client)],
) -> GapAnalysisService:
    """组装只负责语义差距说明的 Service。"""
    return GapAnalysisService(model)


def get_job_compare_service(
    job_service: Annotated[JobStorageService, Depends(get_job_storage_service)],
    analysis_service: Annotated[AnalysisStorageService, Depends(get_analysis_storage_service)],
    gap_service: Annotated[GapAnalysisService, Depends(get_gap_analysis_service)],
) -> JobCompareService:
    """组装历史 JD、规则匹配和差距分析编排服务。"""
    return JobCompareService(
        job_service=job_service,
        analysis_service=analysis_service,
        gap_analysis_service=gap_service,
    )


def get_comparison_job_agent(
    user_id: Annotated[int, Path(gt=0)],
    model: Annotated[OpenAICompatibleClient, Depends(get_llm_client)],
    profile_service: Annotated[ProfileStorageService, Depends(get_profile_storage_service)],
    job_service: Annotated[JobStorageService, Depends(get_job_storage_service)],
    analysis_service: Annotated[AnalysisStorageService, Depends(get_analysis_storage_service)],
    compare_service: Annotated[JobCompareService, Depends(get_job_compare_service)],
) -> JobAgent:
    """组装带 compare_jobs Tool 的 Job Agent。"""
    return JobAgent(
        model=model,
        user_id=user_id,
        profile_service=profile_service,
        job_service=job_service,
        analysis_service=analysis_service,
        job_compare_service=compare_service,
    )


def get_session_service(
    client: Annotated[Redis, Depends(get_redis_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionService:
    """组装 Redis Session、Memory、Cache 与 Agent 编排服务。"""
    return SessionService(
        session_store=SessionStore(client, ttl_seconds=settings.session_ttl_seconds),
        conversation_memory=ConversationMemory(
            client,
            max_turns=settings.conversation_max_turns,
            ttl_seconds=settings.session_ttl_seconds,
        ),
        analysis_cache=AnalysisContextCache(
            client,
            ttl_seconds=settings.agent_cache_ttl_seconds,
        ),
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


@router.post(
    "/users/{user_id}/agents/job/compare",
    response_model=ApiResponse[JobAgentComparisonResponse],
)
async def compare_jobs_with_agent(
    request: JobComparisonRequest,
    agent: Annotated[JobAgent, Depends(get_comparison_job_agent)],
) -> ApiResponse[JobAgentComparisonResponse]:
    """比较历史或新粘贴岗位，并返回技能差距与确定性排名。"""
    return ApiResponse(data=await agent.compare(request))


@router.post(
    "/users/{user_id}/agents/job/chat",
    response_model=ApiResponse[JobAgentSessionResponse],
)
async def chat_with_job_agent(
    user_id: Annotated[int, Path(gt=0)],
    request: JobAgentSessionRequest,
    agent: Annotated[JobAgent, Depends(get_session_job_agent)],
    service: Annotated[SessionService, Depends(get_session_service)],
) -> ApiResponse[JobAgentSessionResponse]:
    """使用 session_id 延续 Job Agent 的最近 N 轮会话。"""
    return ApiResponse(data=await service.chat(user_id=user_id, request=request, agent=agent))


@router.get(
    "/users/{user_id}/agents/job/sessions/{session_id}",
    response_model=ApiResponse[JobAgentSessionState],
)
async def get_job_agent_session(
    user_id: Annotated[int, Path(gt=0)],
    session_id: Annotated[
        str,
        Path(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    ],
    service: Annotated[SessionService, Depends(get_session_service)],
) -> ApiResponse[JobAgentSessionState]:
    """查看当前用户指定 Session 的最近对话与缓存状态。"""
    return ApiResponse(data=await service.get_state(user_id=user_id, session_id=session_id))
