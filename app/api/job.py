"""职位描述相关接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_llm_client
from app.llm.client import OpenAICompatibleClient
from app.schemas.common import ApiResponse
from app.schemas.job import JDParseRequest, JDParseResult
from app.services.jd_parser_service import JDParserService

router = APIRouter(prefix="/jobs", tags=["Jobs"])


def get_jd_parser_service(
    client: Annotated[OpenAICompatibleClient, Depends(get_llm_client)],
) -> JDParserService:
    """根据环境配置组装 JD 解析服务，便于测试时替换依赖。"""
    return JDParserService(client)


@router.post("/parse", response_model=ApiResponse[JDParseResult])
async def parse_job_description(
    request: JDParseRequest,
    service: Annotated[JDParserService, Depends(get_jd_parser_service)],
) -> ApiResponse[JDParseResult]:
    """调用大模型解析 JD，并返回通过 Pydantic 校验的结构化结果。"""
    result = await service.parse(request.jd_text)
    return ApiResponse(data=result)
