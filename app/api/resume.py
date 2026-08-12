"""简历上传与解析接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.dependencies import get_llm_client
from app.api.file_validation import read_validated_pdf
from app.core.config import Settings, get_settings
from app.llm.client import OpenAICompatibleClient
from app.parsers.pdf_parser import PDFParser
from app.schemas.common import ApiResponse
from app.schemas.resume import ResumeParseResult
from app.services.resume_parser_service import ResumeParserService

router = APIRouter(prefix="/resumes", tags=["Resumes"])


def get_resume_parser_service(
    client: Annotated[OpenAICompatibleClient, Depends(get_llm_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ResumeParserService:
    """组装简历解析服务及其 PDF 解析器。"""
    return ResumeParserService(
        PDFParser(max_pages=settings.resume_max_pages),
        client,
        max_text_chars=settings.resume_max_text_chars,
    )


@router.post("/parse", response_model=ApiResponse[ResumeParseResult])
async def parse_resume(
    file: Annotated[UploadFile, File(description="PDF 简历文件")],
    service: Annotated[ResumeParserService, Depends(get_resume_parser_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApiResponse[ResumeParseResult]:
    """读取上传的 PDF，并返回经过 Schema 校验的简历结构。"""
    _, content = await read_validated_pdf(file, settings)
    result = await service.parse(content)
    return ApiResponse(data=result)
