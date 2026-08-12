"""阶段 5 数据库持久化工作流接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.file_validation import read_validated_pdf
from app.api.job import get_jd_parser_service
from app.api.match import get_match_service
from app.api.profile import get_profile_service
from app.api.resume import get_resume_parser_service
from app.core.config import Settings, get_settings
from app.db.database import get_db_session
from app.repository.analysis_repository import AnalysisRepository
from app.repository.job_repository import JobRepository
from app.repository.profile_repository import ProfileRepository
from app.repository.resume_repository import ResumeRepository
from app.repository.user_repository import UserRepository
from app.schemas.common import ApiResponse
from app.schemas.persistence import (
    AnalysisCreateRequest,
    AnalysisRecord,
    JobParseStoredRequest,
    JobRecord,
    ProfileBuildStoredRequest,
    ProfileRecord,
    ResumeRecord,
    UserCreateRequest,
    UserRecord,
)
from app.services.analysis_storage_service import AnalysisStorageService
from app.services.jd_parser_service import JDParserService
from app.services.job_storage_service import JobStorageService
from app.services.match_service import MatchService
from app.services.profile_service import CandidateProfileService
from app.services.profile_storage_service import ProfileStorageService
from app.services.resume_parser_service import ResumeParserService
from app.services.resume_storage_service import ResumeStorageService
from app.services.user_service import UserService

router = APIRouter(tags=["Persistence"])

UserId = Annotated[int, Path(gt=0)]


def get_user_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserService:
    """组装用户持久化 Service。"""
    return UserService(UserRepository(session))


def get_resume_storage_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    parser_service: Annotated[ResumeParserService, Depends(get_resume_parser_service)],
) -> ResumeStorageService:
    """组装 Resume 持久化 Service。"""
    return ResumeStorageService(
        parser_service,
        ResumeRepository(session),
        UserRepository(session),
    )


def get_profile_storage_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    builder_service: Annotated[CandidateProfileService, Depends(get_profile_service)],
) -> ProfileStorageService:
    """组装 Profile 持久化 Service。"""
    return ProfileStorageService(
        builder_service,
        ProfileRepository(session),
        ResumeRepository(session),
        UserRepository(session),
    )


def get_job_storage_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    parser_service: Annotated[JDParserService, Depends(get_jd_parser_service)],
) -> JobStorageService:
    """组装 JD 持久化 Service。"""
    return JobStorageService(
        parser_service,
        JobRepository(session),
        UserRepository(session),
    )


def get_analysis_storage_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    match_service: Annotated[MatchService, Depends(get_match_service)],
) -> AnalysisStorageService:
    """组装岗位分析持久化 Service。"""
    return AnalysisStorageService(
        match_service,
        AnalysisRepository(session),
        JobRepository(session),
        ProfileRepository(session),
        ResumeRepository(session),
        UserRepository(session),
    )


@router.post(
    "/users",
    response_model=ApiResponse[UserRecord],
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    request: UserCreateRequest,
    service: Annotated[UserService, Depends(get_user_service)],
) -> ApiResponse[UserRecord]:
    """创建最小用户记录。"""
    return ApiResponse(data=await service.create(request))


@router.post(
    "/users/{user_id}/resumes/parse",
    response_model=ApiResponse[ResumeRecord],
    status_code=status.HTTP_201_CREATED,
)
async def parse_and_save_resume(
    user_id: UserId,
    file: Annotated[UploadFile, File(description="PDF 简历文件")],
    service: Annotated[ResumeStorageService, Depends(get_resume_storage_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApiResponse[ResumeRecord]:
    """解析 PDF Resume，并保存结构化结果。"""
    filename, content = await read_validated_pdf(file, settings)
    record = await service.parse_and_save(
        user_id=user_id,
        filename=filename,
        pdf_content=content,
    )
    return ApiResponse(data=record)


@router.post(
    "/users/{user_id}/profiles/build",
    response_model=ApiResponse[ProfileRecord],
    status_code=status.HTTP_201_CREATED,
)
async def build_and_save_profile(
    user_id: UserId,
    request: ProfileBuildStoredRequest,
    service: Annotated[ProfileStorageService, Depends(get_profile_storage_service)],
) -> ApiResponse[ProfileRecord]:
    """从已保存 Resume 构建并保存当前 Profile。"""
    record = await service.build_and_save(user_id=user_id, resume_id=request.resume_id)
    return ApiResponse(data=record)


@router.get(
    "/users/{user_id}/profile",
    response_model=ApiResponse[ProfileRecord],
)
async def get_current_profile(
    user_id: UserId,
    service: Annotated[ProfileStorageService, Depends(get_profile_storage_service)],
) -> ApiResponse[ProfileRecord]:
    """查看用户当前 Profile。"""
    return ApiResponse(data=await service.get_current(user_id))


@router.post(
    "/users/{user_id}/jobs/parse",
    response_model=ApiResponse[JobRecord],
    status_code=status.HTTP_201_CREATED,
)
async def parse_and_save_job(
    user_id: UserId,
    request: JobParseStoredRequest,
    service: Annotated[JobStorageService, Depends(get_job_storage_service)],
) -> ApiResponse[JobRecord]:
    """解析并保存 JD。"""
    return ApiResponse(data=await service.parse_and_save(user_id=user_id, jd_text=request.jd_text))


@router.get(
    "/users/{user_id}/jobs",
    response_model=ApiResponse[list[JobRecord]],
)
async def list_job_history(
    user_id: UserId,
    service: Annotated[JobStorageService, Depends(get_job_storage_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[list[JobRecord]]:
    """查看用户历史 JD。"""
    records = await service.list_history(user_id, limit=limit, offset=offset)
    return ApiResponse(data=records)


@router.post(
    "/users/{user_id}/job-analyses",
    response_model=ApiResponse[AnalysisRecord],
    status_code=status.HTTP_201_CREATED,
)
async def analyze_and_save_job(
    user_id: UserId,
    request: AnalysisCreateRequest,
    service: Annotated[AnalysisStorageService, Depends(get_analysis_storage_service)],
) -> ApiResponse[AnalysisRecord]:
    """使用当前 Profile 分析并保存指定岗位。"""
    return ApiResponse(data=await service.analyze_and_save(user_id=user_id, job_id=request.job_id))


@router.get(
    "/users/{user_id}/job-analyses",
    response_model=ApiResponse[list[AnalysisRecord]],
)
async def list_analysis_history(
    user_id: UserId,
    service: Annotated[AnalysisStorageService, Depends(get_analysis_storage_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[list[AnalysisRecord]]:
    """查看用户历史岗位分析。"""
    records = await service.list_history(user_id, limit=limit, offset=offset)
    return ApiResponse(data=records)
