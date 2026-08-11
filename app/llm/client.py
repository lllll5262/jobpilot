"""基于 httpx 的 OpenAI-compatible API 客户端。"""

import json
import logging
from typing import Any, Literal, Protocol

import httpx

logger = logging.getLogger(__name__)

LLMProvider = Literal["qwen", "deepseek"]


class JSONGenerator(Protocol):
    """应用服务依赖的最小 LLM JSON 生成接口。"""

    async def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """生成 JSON 对象。"""
        ...


class LLMClientError(Exception):
    """LLM 客户端异常基类。"""


class LLMConfigurationError(LLMClientError):
    """LLM 配置不完整。"""


class LLMTimeoutError(LLMClientError):
    """LLM 请求超时。"""


class LLMResponseError(LLMClientError):
    """LLM 返回内容不符合兼容协议或 JSON 格式。"""


class OpenAICompatibleClient:
    """调用 Qwen 或 DeepSeek 的 OpenAI-compatible Chat Completions API。"""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        api_key: str | None,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._provider = provider
        self._api_key = api_key.strip() if api_key else None
        self._base_url = f"{base_url.rstrip('/')}/"
        self._model = model
        self._timeout_seconds = timeout_seconds
        # transport 仅用于依赖注入，生产环境默认使用 httpx 的网络传输层。
        self._transport = transport

    async def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """请求模型输出 JSON，并解析为字典。"""
        if not self._api_key:
            raise LLMConfigurationError("LLM API key is not configured")

        request_body: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        if self._provider == "qwen":
            # Qwen 的 JSON Mode 与思考模式不能同时开启。
            request_body["enable_thinking"] = False

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post("chat/completions", json=request_body)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("LLM request timed out") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning("LLM HTTP 请求失败 status_code=%s", exc.response.status_code)
            raise LLMClientError("LLM request failed") from exc
        except httpx.HTTPError as exc:
            logger.warning("LLM 网络请求失败 error_type=%s", type(exc).__name__)
            raise LLMClientError("LLM request failed") from exc

        try:
            response_body = response.json()
            content = response_body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("LLM returned an invalid API response") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("LLM returned empty content")

        try:
            structured_data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMResponseError("LLM content is not valid JSON") from exc

        if not isinstance(structured_data, dict):
            raise LLMResponseError("LLM JSON output must be an object")
        return structured_data
