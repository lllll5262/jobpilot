"""职位描述相关接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.llm.client import OpenAICompatibleClient
from app.schemas.common import ApiResponse
from app.schemas.job import JDParseRequest, JDParseResult
from app.services.jd_parser_service import JDParserService

router = APIRouter(prefix="/jobs", tags=["Jobs"])


def get_jd_parser_service() -> JDParserService:
    """根据环境配置组装 JD 解析服务，便于测试时替换依赖。"""
    settings = get_settings()
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key is not None else None
    client = OpenAICompatibleClient(
        provider=settings.llm_provider,
        api_key=api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    return JDParserService(client)


@router.post("/parse", response_model=ApiResponse[JDParseResult])
async def parse_job_description(
    request: JDParseRequest,
    service: Annotated[JDParserService, Depends(get_jd_parser_service)],
) -> ApiResponse[JDParseResult]:
    """调用大模型解析 JD，并返回通过 Pydantic 校验的结构化结果。"""
    result = await service.parse(request.jd_text)
    return ApiResponse(data=result)
