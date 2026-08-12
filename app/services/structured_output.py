"""LLM 结构化输出服务的共享校验流程。"""

import json
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
    validation_retries: int = 0,
) -> ModelT:
    """调用 LLM 并统一完成错误映射与 Pydantic Schema 校验。"""
    current_user_prompt = user_prompt
    validation_error: ValidationError | None = None
    for attempt in range(validation_retries + 1):
        structured_data = await _request_json(
            llm_client=llm_client,
            system_prompt=system_prompt,
            user_prompt=current_user_prompt,
        )
        try:
            return schema.model_validate(structured_data)
        except ValidationError as exc:
            validation_error = exc
            errors = [
                {
                    "location": ".".join(str(part) for part in error["loc"]),
                    "type": error["type"],
                }
                for error in exc.errors(include_url=False, include_input=False)
            ]
            logger.warning(
                "LLM 结构化输出校验失败 context=%s attempt=%s errors=%s",
                log_context,
                attempt + 1,
                errors,
            )
            if attempt < validation_retries:
                current_user_prompt = (
                    f"{user_prompt}\n\n上一次 JSON 未通过校验，请按 Schema 完整重写。"
                    f"错误字段：{json.dumps(errors, ensure_ascii=False)}"
                )

    raise AppException(
        "LLM output failed schema validation",
        code=50202,
        status_code=502,
    ) from validation_error


async def _request_json(
    *,
    llm_client: JSONGenerator,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, object]:
    """统一映射一次 LLM 网络和协议错误。"""
    try:
        return await llm_client.generate_json(
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
