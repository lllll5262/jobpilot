"""简历上传与解析接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.dependencies import get_llm_client
from app.core.config import Settings, get_settings
from app.core.exceptions import AppException
from app.llm.client import OpenAICompatibleClient
from app.parsers.pdf_parser import PDFParser
from app.schemas.common import ApiResponse
from app.schemas.resume import ResumeParseResult
from app.services.resume_parser_service import ResumeParserService

router = APIRouter(prefix="/resumes", tags=["Resumes"])

ALLOWED_PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}


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
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise AppException("Only PDF files are supported", code=40010, status_code=400)
    if file.content_type not in ALLOWED_PDF_CONTENT_TYPES:
        raise AppException("Invalid PDF content type", code=40011, status_code=400)

    max_bytes = settings.resume_max_file_size_mb * 1024 * 1024
    try:
        content = await file.read(max_bytes + 1)
    finally:
        await file.close()

    if len(content) > max_bytes:
        raise AppException(
            f"PDF file exceeds the {settings.resume_max_file_size_mb} MB limit",
            code=41301,
            status_code=413,
        )
    if not content.startswith(b"%PDF-"):
        raise AppException("Invalid PDF file signature", code=40012, status_code=400)

    result = await service.parse(content)
    return ApiResponse(data=result)
