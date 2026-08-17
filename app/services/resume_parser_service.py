"""简历解析应用服务。"""

import logging
import re
from dataclasses import dataclass

from app.core.exceptions import AppException
from app.llm.client import JSONGenerator
from app.llm.prompts.resume_parser import (
    build_resume_parser_system_prompt,
    build_resume_parser_user_prompt,
)
from app.parsers.base import (
    BaseDocumentParser,
    DocumentLimitError,
    DocumentParserError,
    EncryptedDocumentError,
)
from app.schemas.resume import ResumeParseResult
from app.services.structured_output import generate_structured_output

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ParsedResumeDocument:
    """同时返回结构化简历和清洗后的完整原文，供 MongoDB/Milvus 存储。"""

    resume: ResumeParseResult
    cleaned_text: str


def clean_resume_text(text: str) -> str:
    """清除 PDF 常见控制字符、行尾空白和过多空行。"""
    normalized = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n")]
    cleaned = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


class ResumeParserService:
    """编排 PDF 解析、文本清洗、LLM 调用和 Schema 校验。"""

    def __init__(
        self,
        document_parser: BaseDocumentParser,
        llm_client: JSONGenerator,
        *,
        max_text_chars: int,
    ) -> None:
        self._document_parser = document_parser
        self._llm_client = llm_client
        self._max_text_chars = max_text_chars

    async def parse_with_source(self, pdf_content: bytes) -> ParsedResumeDocument:
        """解析 PDF，并保留用于溯源和父子分块的清洗后完整文本。"""
        try:
            parsed_document = self._document_parser.parse(pdf_content)
        except EncryptedDocumentError as exc:
            raise AppException(
                "Encrypted PDF is not supported",
                code=42211,
                status_code=422,
            ) from exc
        except DocumentLimitError as exc:
            raise AppException(
                str(exc),
                code=41302,
                status_code=413,
            ) from exc
        except DocumentParserError as exc:
            raise AppException(
                "Invalid PDF document",
                code=42210,
                status_code=422,
            ) from exc

        cleaned_text = clean_resume_text(parsed_document.text)
        if not cleaned_text:
            raise AppException(
                "PDF contains no extractable text; OCR is not supported",
                code=42212,
                status_code=422,
            )
        if len(cleaned_text) > self._max_text_chars:
            raise AppException(
                "Extracted resume text exceeds the allowed limit",
                code=41303,
                status_code=413,
            )

        result = await generate_structured_output(
            llm_client=self._llm_client,
            system_prompt=build_resume_parser_system_prompt(),
            user_prompt=build_resume_parser_user_prompt(cleaned_text),
            schema=ResumeParseResult,
            log_context="resume_parser",
        )

        logger.info(
            "简历解析成功 pages=%s skills_count=%s projects_count=%s internships_count=%s",
            parsed_document.page_count,
            len(result.skills),
            len(result.projects),
            len(result.internships),
        )
        return ParsedResumeDocument(
            resume=result,
            cleaned_text=cleaned_text,
        )
