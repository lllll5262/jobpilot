"""岗位匹配接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_llm_client
from app.llm.client import OpenAICompatibleClient
from app.schemas.common import ApiResponse
from app.schemas.match import MatchRequest, MatchResult
from app.services.match_service import MatchService
from app.services.scoring_service import ScoringService

router = APIRouter(prefix="/matches", tags=["Matches"])


def get_match_service(
    client: Annotated[OpenAICompatibleClient, Depends(get_llm_client)],
) -> MatchService:
    """组装语义分析客户端和确定性算分服务。"""
    return MatchService(client, ScoringService())


@router.post("/evaluate", response_model=ApiResponse[MatchResult])
async def evaluate_match(
    request: MatchRequest,
    service: Annotated[MatchService, Depends(get_match_service)],
) -> ApiResponse[MatchResult]:
    """组合 Resume、Profile 和 JD，返回岗位匹配结果。"""
    result = await service.match(
        resume=request.resume,
        profile=request.profile,
        job=request.job,
    )
    return ApiResponse(data=result)
