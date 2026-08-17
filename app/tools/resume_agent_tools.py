"""Resume Agent Tool 适配层。"""

from typing import Any

from app.core.exceptions import AppException
from app.schemas.resume_agent import ResumeAgentPayload
from app.services.profile_storage_service import ProfileStorageService
from app.services.resume_optimization_service import ResumeOptimizationService
from app.services.resume_rag_service import ResumeRagService
from app.services.resume_storage_service import ResumeStorageService


class GetResumeTool:
    """读取指定或最新结构化简历。"""

    name = "get_resume"

    def __init__(self, *, user_id: int, service: ResumeStorageService) -> None:
        self._user_id = user_id
        self._service = service

    async def invoke(self, payload: ResumeAgentPayload) -> dict[str, Any]:
        result = await self._service.get(user_id=self._user_id, resume_id=payload.resume_id)
        return result.model_dump(mode="json")


class AnswerResumeTool:
    """通过 Milvus 检索和受来源约束的生成链路回答简历事实问题。"""

    name = "answer_resume"

    def __init__(
        self,
        *,
        user_id: int,
        service: ResumeRagService,
        retrieval_limit: int,
    ) -> None:
        self._user_id = user_id
        self._service = service
        self._retrieval_limit = retrieval_limit

    async def invoke(self, payload: ResumeAgentPayload) -> dict[str, Any]:
        if payload.query is None:
            raise AppException("query is required", code=42222, status_code=422)
        result = await self._service.answer(
            user_id=self._user_id,
            resume_id=payload.resume_id,
            query=payload.query,
            limit=self._retrieval_limit,
        )
        return result.model_dump(mode="json")


class GetProfileTool:
    """读取当前 Candidate Profile。"""

    name = "get_profile"

    def __init__(self, *, user_id: int, service: ProfileStorageService) -> None:
        self._user_id = user_id
        self._service = service

    async def invoke(self, payload: ResumeAgentPayload) -> dict[str, Any]:
        del payload
        result = await self._service.get_current(self._user_id)
        return result.model_dump(mode="json")


class UpdateProfileTool:
    """从指定简历重建当前 Profile。"""

    name = "update_profile"

    def __init__(self, *, user_id: int, service: ProfileStorageService) -> None:
        self._user_id = user_id
        self._service = service

    async def invoke(self, payload: ResumeAgentPayload) -> dict[str, Any]:
        if payload.resume_id is None:
            raise AppException("resume_id is required", code=42220, status_code=422)
        result = await self._service.build_and_save(
            user_id=self._user_id,
            resume_id=payload.resume_id,
        )
        return result.model_dump(mode="json")


class OptimizeResumeTool:
    """调用 ResumeOptimizationService 生成事实受限的修改建议。"""

    name = "optimize_resume"

    def __init__(self, *, user_id: int, service: ResumeOptimizationService) -> None:
        self._user_id = user_id
        self._service = service

    async def invoke(self, payload: ResumeAgentPayload) -> dict[str, Any]:
        if payload.job_id is None:
            raise AppException("job_id is required", code=42221, status_code=422)
        result = await self._service.optimize(
            user_id=self._user_id,
            resume_id=payload.resume_id,
            job_id=payload.job_id,
        )
        return result.model_dump(mode="json")
