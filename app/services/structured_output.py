"""LLM 结构化输出服务的共享校验流程。"""

import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.core.exceptions import AppException
from app.llm.client import (
    JSONGenerator,
    LLMClientError,
    LLMConfigurationError,
    LLMResponseError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)


async def generate_structured_output(
    *,
    llm_client: JSONGenerator,
    system_prompt: str,
    user_prompt: str,
    schema: type[ModelT],
    log_context: str,
) -> ModelT:
    """调用 LLM 并统一完成错误映射与 Pydantic Schema 校验。"""
    try:
        structured_data = await llm_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
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
        return schema.model_validate(structured_data)
    except ValidationError as exc:
        logger.warning(
            "LLM 结构化输出校验失败 context=%s error_count=%s",
            log_context,
            exc.error_count(),
        )
        raise AppException(
            "LLM output failed schema validation",
            code=50202,
            status_code=502,
        ) from exc
