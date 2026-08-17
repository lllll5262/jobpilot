"""阶段 5 数据库持久化工作流接口。"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_llm_client, get_resume_parser_service
from app.api.file_validation import read_validated_pdf
from app.api.job import get_jd_parser_service
from app.api.match import get_match_service
from app.api.profile import get_profile_service
from app.core.config import Settings, get_settings
from app.core.exceptions import AppException
from app.db.database import get_db_session
from app.llm.client import OpenAICompatibleClient
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
    ResumeIngestionStatus,
    ResumeIngestionSubmission,
    ResumeRecord,
    UserCreateRequest,
    UserRecord,
)
from app.schemas.resume_rag import ResumeAnswerRequest, ResumeAnswerResult
from app.schemas.resume_vector import (
    ResumeSearchRequest,
    ResumeSearchResult,
    ResumeSourceRecord,
)
from app.services.analysis_storage_service import AnalysisStorageService
from app.services.jd_parser_service import JDParserService
from app.services.job_storage_service import JobStorageService
from app.services.match_service import MatchService
from app.services.profile_service import CandidateProfileService
from app.services.profile_storage_service import ProfileStorageService
from app.services.resume_content_service import ResumeContentService
from app.services.resume_knowledge_service import ResumeKnowledgeService
from app.services.resume_parser_service import ResumeParserService
from app.services.resume_rag_service import ResumeRagService
from app.services.resume_storage_service import ResumeStorageService
from app.services.user_service import UserService
from app.storage.dependencies import get_resume_object_store
from app.storage.minio_resume_store import MinioResumeObjectStore
from app.tasks.resume_ingestion_queue import (
    ResumeIngestionQueue,
    get_resume_ingestion_queue,
)
from app.vectorstore.dependencies import get_resume_knowledge_service

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
    knowledge_service: Annotated[
        ResumeKnowledgeService,
        Depends(get_resume_knowledge_service),
    ],
    object_store: Annotated[
        MinioResumeObjectStore,
        Depends(get_resume_object_store),
    ],
) -> ResumeStorageService:
    """组装 Resume 持久化 Service。"""
    return ResumeStorageService(
        parser_service,
        ResumeRepository(session),
        UserRepository(session),
        knowledge_service,
        object_store,
    )


def get_resume_rag_service(
    client: Annotated[OpenAICompatibleClient, Depends(get_llm_client)],
    resume_service: Annotated[ResumeStorageService, Depends(get_resume_storage_service)],
) -> ResumeRagService:
    """组装简历检索增强问答 Service。"""
    return ResumeRagService(llm_client=client, resume_service=resume_service)


def get_profile_storage_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    builder_service: Annotated[CandidateProfileService, Depends(get_profile_service)],
    object_store: Annotated[MinioResumeObjectStore, Depends(get_resume_object_store)],
) -> ProfileStorageService:
    """组装 Profile 持久化 Service。"""
    return ProfileStorageService(
        builder_service,
        ProfileRepository(session),
        ResumeRepository(session),
        UserRepository(session),
        ResumeContentService(object_store),
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
    object_store: Annotated[MinioResumeObjectStore, Depends(get_resume_object_store)],
) -> AnalysisStorageService:
    """组装岗位分析持久化 Service。"""
    return AnalysisStorageService(
        match_service,
        AnalysisRepository(session),
        JobRepository(session),
        ProfileRepository(session),
        ResumeRepository(session),
        UserRepository(session),
        ResumeContentService(object_store),
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
    return ApiResponse(
        message="简历已上传过" if record.duplicate else "success",
        data=record,
    )


@router.post(
    "/users/{user_id}/resumes/parse-async",
    response_model=ApiResponse[ResumeIngestionSubmission],
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_resume_ingestion(
    user_id: UserId,
    file: Annotated[UploadFile, File(description="PDF 简历文件")],
    service: Annotated[ResumeStorageService, Depends(get_resume_storage_service)],
    queue: Annotated[ResumeIngestionQueue, Depends(get_resume_ingestion_queue)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApiResponse[ResumeIngestionSubmission]:
    """将 PDF 暂存到 MinIO，并发布不含文件二进制的 Celery 入库任务。"""
    filename, content = await read_validated_pdf(file, settings)
    preparation = await service.prepare_async_ingestion(
        user_id=user_id,
        filename=filename,
        pdf_content=content,
    )
    if preparation.duplicate is not None:
        return ApiResponse(
            message="简历已上传过",
            data=ResumeIngestionSubmission(
                status="completed",
                duplicate=True,
                resume=preparation.duplicate,
            )
        )

    stored_object = preparation.stored_object
    if stored_object is None:
        raise AppException("Resume staging failed", code=50322, status_code=503)
    try:
        task_id = await asyncio.to_thread(
            queue.enqueue,
            user_id=user_id,
            filename=filename,
            doc_hash=preparation.doc_hash,
            stored_object=stored_object,
        )
    except Exception as exc:
        await service.discard_staged(stored_object)
        raise AppException(
            "Resume ingestion queue is unavailable",
            code=50322,
            status_code=503,
        ) from exc
    return ApiResponse(
        data=ResumeIngestionSubmission(task_id=task_id, status="queued")
    )


@router.get(
    "/users/{user_id}/resumes/ingestions/{task_id}",
    response_model=ApiResponse[ResumeIngestionStatus],
)
async def get_resume_ingestion_status(
    user_id: UserId,
    task_id: Annotated[str, Path(min_length=40, max_length=80)],
    queue: Annotated[ResumeIngestionQueue, Depends(get_resume_ingestion_queue)],
) -> ApiResponse[ResumeIngestionStatus]:
    """查询 Celery 任务状态；失败结果不会暴露 Worker 内部异常。"""
    result = await asyncio.to_thread(queue.get_status, user_id=user_id, task_id=task_id)
    return ApiResponse(data=result)


@router.post(
    "/users/{user_id}/resumes/search",
    response_model=ApiResponse[ResumeSearchResult],
)
async def search_resume_context(
    user_id: UserId,
    request: ResumeSearchRequest,
    service: Annotated[ResumeStorageService, Depends(get_resume_storage_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApiResponse[ResumeSearchResult]:
    """用 Milvus 稠密/稀疏混合排序检索简历，并返回命中子块及父块原文。"""
    matches = await service.search_context(
        user_id=user_id,
        resume_id=request.resume_id,
        query=request.query,
        limit=request.limit or settings.resume_retrieval_limit,
    )
    return ApiResponse(data=ResumeSearchResult(query=request.query, matches=matches))


@router.post(
    "/users/{user_id}/resumes/answer",
    response_model=ApiResponse[ResumeAnswerResult],
)
async def answer_from_resume(
    user_id: UserId,
    request: ResumeAnswerRequest,
    service: Annotated[ResumeRagService, Depends(get_resume_rag_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApiResponse[ResumeAnswerResult]:
    """检索简历父块，并要求 LLM 仅依据检索上下文回答。"""
    result = await service.answer(
        user_id=user_id,
        resume_id=request.resume_id,
        query=request.query,
        limit=request.limit or settings.resume_retrieval_limit,
    )
    return ApiResponse(data=result)


@router.get(
    "/users/{user_id}/resumes/{resume_id}/source",
    response_model=ApiResponse[ResumeSourceRecord],
)
async def get_resume_source(
    user_id: UserId,
    resume_id: Annotated[int, Path(gt=0)],
    service: Annotated[ResumeStorageService, Depends(get_resume_storage_service)],
) -> ApiResponse[ResumeSourceRecord]:
    """返回 MinIO 原始简历的元数据和短时下载地址。"""
    return ApiResponse(data=await service.get_source(user_id=user_id, resume_id=resume_id))


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
