"""候选人能力画像接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_llm_client
from app.llm.client import OpenAICompatibleClient
from app.schemas.common import ApiResponse
from app.schemas.profile import CandidateProfile, ProfileBuildRequest
from app.services.profile_service import CandidateProfileService

router = APIRouter(prefix="/profiles", tags=["Profiles"])


def get_profile_service(
    client: Annotated[OpenAICompatibleClient, Depends(get_llm_client)],
) -> CandidateProfileService:
    """组装候选人能力画像服务。"""
    return CandidateProfileService(client)


@router.post("/build", response_model=ApiResponse[CandidateProfile])
async def build_candidate_profile(
    request: ProfileBuildRequest,
    service: Annotated[CandidateProfileService, Depends(get_profile_service)],
) -> ApiResponse[CandidateProfile]:
    """根据已解析的 Resume 构建独立能力画像。"""
    profile = await service.build(request.resume)
    return ApiResponse(data=profile)
