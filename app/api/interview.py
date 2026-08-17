"""阶段 10 自适应面试 HTTP 接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.interview_agent import InterviewAgent
from app.api.dependencies import get_llm_client
from app.db.database import get_db_session
from app.llm.client import OpenAICompatibleClient
from app.repository.interview_repository import InterviewRepository
from app.repository.job_repository import JobRepository
from app.repository.profile_repository import ProfileRepository
from app.repository.resume_repository import ResumeRepository
from app.repository.user_repository import UserRepository
from app.schemas.common import ApiResponse
from app.schemas.interview import (
    InterviewAnswerRequest,
    InterviewAnswerResponse,
    InterviewSessionRecord,
    InterviewStartRequest,
)
from app.services.interview_evaluator import InterviewEvaluator
from app.services.interview_service import InterviewService
from app.services.resume_content_service import ResumeContentService
from app.storage.dependencies import get_resume_object_store
from app.storage.minio_resume_store import MinioResumeObjectStore

router = APIRouter(prefix="/users/{user_id}/interviews", tags=["Interview Assistant"])
UserId = Annotated[int, Path(gt=0)]
InterviewId = Annotated[int, Path(gt=0)]


def get_interview_service(
    model: Annotated[OpenAICompatibleClient, Depends(get_llm_client)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    object_store: Annotated[MinioResumeObjectStore, Depends(get_resume_object_store)],
) -> InterviewService:
    """组装面试服务，Tool 只调用该业务层。"""
    return InterviewService(
        llm_client=model,
        evaluator=InterviewEvaluator(model),
        interview_repository=InterviewRepository(session),
        job_repository=JobRepository(session),
        profile_repository=ProfileRepository(session),
        resume_repository=ResumeRepository(session),
        user_repository=UserRepository(session),
        resume_content_service=ResumeContentService(object_store),
    )


def get_interview_agent(
    user_id: UserId,
    service: Annotated[InterviewService, Depends(get_interview_service)],
) -> InterviewAgent:
    """按当前用户组装面试 LangGraph Agent。"""
    return InterviewAgent(user_id=user_id, service=service)


@router.post(
    "",
    response_model=ApiResponse[InterviewSessionRecord],
    status_code=status.HTTP_201_CREATED,
)
async def start_interview(
    request: InterviewStartRequest,
    agent: Annotated[InterviewAgent, Depends(get_interview_agent)],
) -> ApiResponse[InterviewSessionRecord]:
    """根据当前简历生成第一道面试题。"""
    return ApiResponse(data=await agent.start(request))


@router.post(
    "/{interview_id}/answers",
    response_model=ApiResponse[InterviewAnswerResponse],
)
async def answer_interview(
    interview_id: InterviewId,
    request: InterviewAnswerRequest,
    agent: Annotated[InterviewAgent, Depends(get_interview_agent)],
) -> ApiResponse[InterviewAnswerResponse]:
    """评价当前答案，指出错误，并持续返回下一题。"""
    return ApiResponse(
        data=await agent.answer(session_id=interview_id, request=request)
    )


@router.get(
    "/{interview_id}",
    response_model=ApiResponse[InterviewSessionRecord],
)
async def get_interview(
    user_id: UserId,
    interview_id: InterviewId,
    service: Annotated[InterviewService, Depends(get_interview_service)],
) -> ApiResponse[InterviewSessionRecord]:
    """查看全部题目、用户回答、错误说明和正确答案。"""
    return ApiResponse(
        data=await service.get_session(user_id=user_id, session_id=interview_id)
    )
