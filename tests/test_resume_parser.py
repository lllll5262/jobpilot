"""PDF 简历解析功能测试。"""

import asyncio
from typing import Any

import httpx
import pymupdf
import pytest

from app.api.resume import get_resume_parser_service
from app.core.exceptions import AppException
from app.main import app
from app.parsers.pdf_parser import PDFParser
from app.schemas.resume import ResumeParseResult
from app.services.resume_parser_service import ResumeParserService, clean_resume_text

RESUME_TEXT = """Jane Doe
Email: jane@example.com
Education: Example University, Bachelor of Computer Science, 2020-2024
Skills: Python, FastAPI, MySQL
Project: JobPilot - Resume parser built with FastAPI and PyMuPDF
Internship: Backend Intern at Example Tech, 2023
Certificate: AWS Certified Cloud Practitioner
"""

PARSED_RESUME = {
    "personal_info": {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": None,
        "location": None,
    },
    "education": [
        {
            "school": "Example University",
            "degree": "Bachelor",
            "major": "Computer Science",
            "start_date": "2020",
            "end_date": "2024",
        }
    ],
    "skills": ["Python", "FastAPI", "MySQL"],
    "projects": [
        {
            "name": "JobPilot",
            "role": None,
            "description": "Resume parser built with FastAPI and PyMuPDF",
            "technologies": ["FastAPI", "PyMuPDF"],
            "start_date": None,
            "end_date": None,
        }
    ],
    "internships": [
        {
            "company": "Example Tech",
            "position": "Backend Intern",
            "description": None,
            "start_date": "2023",
            "end_date": None,
        }
    ],
    "certificates": [
        {
            "name": "AWS Certified Cloud Practitioner",
            "issuer": None,
            "date": None,
        }
    ],
}


def build_text_pdf(text: str = RESUME_TEXT, *, page_count: int = 1) -> bytes:
    """生成带文本层的最小 PDF 测试夹具。"""
    document = pymupdf.open()
    for _ in range(page_count):
        page = document.new_page()
        text_writer = pymupdf.TextWriter(page.rect)
        y_position = 72
        for line in text.splitlines():
            text_writer.append((72, y_position), line)
            y_position += 18
        text_writer.write_text(page)
    content = document.tobytes()
    document.close()
    return content


class StubLLMClient:
    """记录清洗后输入并返回固定 Resume JSON。"""

    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        self.user_prompt: str | None = None

    async def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        assert "JSON" in system_prompt
        self.user_prompt = user_prompt
        return self._result


async def _post_file(
    filename: str,
    content: bytes,
    content_type: str,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.post(
            "/resumes/parse",
            files={"file": (filename, content, content_type)},
        )


def test_pdf_parser_extracts_text() -> None:
    """PyMuPDF 解析器应从真实文本型 PDF 中提取内容。"""
    result = PDFParser(max_pages=20).parse(build_text_pdf())

    assert result.page_count == 1
    assert "Jane Doe" in result.text
    assert "Python, FastAPI, MySQL" in result.text


def test_pdf_parser_rejects_page_limit() -> None:
    """页数超过配置限制时不应继续提取或调用 LLM。"""
    service = ResumeParserService(
        PDFParser(max_pages=1),
        StubLLMClient(PARSED_RESUME),
        max_text_chars=50_000,
    )

    with pytest.raises(AppException) as exc_info:
        asyncio.run(service.parse(build_text_pdf(page_count=2)))

    assert exc_info.value.code == 41302


def test_clean_resume_text_removes_pdf_noise() -> None:
    """清洗逻辑应移除控制字符、行尾空白和过多空行。"""
    assert clean_resume_text("Name\x00  \r\n\r\n\r\n Skills:\tPython ") == (
        "Name\n\nSkills: Python"
    )


def test_resume_parser_service_returns_valid_schema() -> None:
    """完整服务流程应输出经过 Resume Schema 校验的数据。"""
    llm_client = StubLLMClient(PARSED_RESUME)
    service = ResumeParserService(
        PDFParser(max_pages=20),
        llm_client,
        max_text_chars=50_000,
    )

    result = asyncio.run(service.parse(build_text_pdf()))

    assert result == ResumeParseResult.model_validate(PARSED_RESUME)
    assert llm_client.user_prompt is not None
    assert "Jane Doe" in llm_client.user_prompt


def test_resume_parser_service_rejects_invalid_llm_schema() -> None:
    """字段缺失的模型 JSON 不能进入接口响应。"""
    service = ResumeParserService(
        PDFParser(max_pages=20),
        StubLLMClient({"skills": ["Python"]}),
        max_text_chars=50_000,
    )

    with pytest.raises(AppException) as exc_info:
        asyncio.run(service.parse(build_text_pdf()))

    assert exc_info.value.code == 50202


def test_resume_parser_service_rejects_scanned_pdf_without_text() -> None:
    """无文本层 PDF 应提示当前阶段不支持 OCR。"""
    service = ResumeParserService(
        PDFParser(max_pages=20),
        StubLLMClient(PARSED_RESUME),
        max_text_chars=50_000,
    )

    with pytest.raises(AppException) as exc_info:
        asyncio.run(service.parse(build_text_pdf("")))

    assert exc_info.value.code == 42212


def test_parse_resume_endpoint() -> None:
    """上传接口应完成真实 PDF 提取并返回统一结构。"""

    def build_service() -> ResumeParserService:
        return ResumeParserService(
            PDFParser(max_pages=20),
            StubLLMClient(PARSED_RESUME),
            max_text_chars=50_000,
        )

    app.dependency_overrides[get_resume_parser_service] = build_service
    try:
        response = asyncio.run(_post_file("resume.pdf", build_text_pdf(), "application/pdf"))
    finally:
        app.dependency_overrides.pop(get_resume_parser_service, None)

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "success",
        "data": PARSED_RESUME,
    }


def test_parse_resume_endpoint_rejects_non_pdf() -> None:
    """文件扩展名和签名不符合 PDF 时应在调用服务前拒绝。"""
    response = asyncio.run(_post_file("resume.txt", b"plain text", "text/plain"))

    assert response.status_code == 400
    assert response.json()["code"] == 40010


def test_parse_resume_endpoint_rejects_fake_pdf() -> None:
    """仅修改扩展名和 MIME 类型不能绕过 PDF 文件签名校验。"""
    response = asyncio.run(_post_file("resume.pdf", b"plain text", "application/pdf"))

    assert response.status_code == 400
    assert response.json()["code"] == 40012
