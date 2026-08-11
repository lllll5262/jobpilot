"""JD 解析应用服务。"""

import logging
from typing import Any, Protocol

from pydantic import ValidationError

from app.core.exceptions import AppException
from app.llm.client import (
    LLMClientError,
    LLMConfigurationError,
    LLMResponseError,
    LLMTimeoutError,
)
from app.llm.prompts.jd_parser import (
    build_jd_parser_system_prompt,
    build_jd_parser_user_prompt,
)
from app.schemas.job import JDParseResult

logger = logging.getLogger(__name__)


class JSONGenerator(Protocol):
    """JD 服务所需的最小 LLM 能力接口。"""

    async def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """生成 JSON 对象。"""
        ...


class JDParserService:
    """编排 Prompt、LLM 调用和 Pydantic 结构化校验。"""

    def __init__(self, llm_client: JSONGenerator) -> None:
        self._llm_client = llm_client

    async def parse(self, jd_text: str) -> JDParseResult:
        """解析 JD；模型输出只有通过 Schema 校验后才能返回。"""
        try:
            structured_data = await self._llm_client.generate_json(
                system_prompt=build_jd_parser_system_prompt(),
                user_prompt=build_jd_parser_user_prompt(jd_text),
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
            return JDParseResult.model_validate(structured_data)
        except ValidationError as exc:
            logger.warning("LLM 结构化输出校验失败 error_count=%s", exc.error_count())
            raise AppException(
                "LLM output failed schema validation",
                code=50202,
                status_code=502,
            ) from exc
