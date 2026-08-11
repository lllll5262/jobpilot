"""简历解析应用服务。"""

import logging
import re

from pydantic import ValidationError

from app.core.exceptions import AppException
from app.llm.client import (
    JSONGenerator,
    LLMClientError,
    LLMConfigurationError,
    LLMResponseError,
    LLMTimeoutError,
)
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

logger = logging.getLogger(__name__)


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

    async def parse(self, pdf_content: bytes) -> ResumeParseResult:
        """解析文本型 PDF；扫描件会因无可提取文本而被明确拒绝。"""
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

        try:
            structured_data = await self._llm_client.generate_json(
                system_prompt=build_resume_parser_system_prompt(),
                user_prompt=build_resume_parser_user_prompt(cleaned_text),
            )
        except LLMConfigurationError as exc:
            raise AppException(
                "LLM is not configured",
                code=50301,
                status_code=503,
            ) from exc
        except LLMTimeoutError as exc:
            raise AppException(
                "LLM request timed out",
                code=50401,
                status_code=504,
            ) from exc
        except LLMResponseError as exc:
            raise AppException(
                "LLM service returned an invalid response",
                code=50201,
                status_code=502,
            ) from exc
        except LLMClientError as exc:
            raise AppException(
                "LLM service request failed",
                code=50201,
                status_code=502,
            ) from exc

        try:
            result = ResumeParseResult.model_validate(structured_data)
        except ValidationError as exc:
            logger.warning("LLM 简历结构化输出校验失败 error_count=%s", exc.error_count())
            raise AppException(
                "LLM output failed schema validation",
                code=50202,
                status_code=502,
            ) from exc

        logger.info(
            "简历解析成功 pages=%s skills_count=%s projects_count=%s internships_count=%s",
            parsed_document.page_count,
            len(result.skills),
            len(result.projects),
            len(result.internships),
        )
        return result
