"""基于 httpx 的 OpenAI-compatible API 客户端。"""

import json
import logging
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

LLMProvider = Literal["qwen", "deepseek", "glm"]


class JSONGenerator(Protocol):
    """应用服务依赖的最小 LLM JSON 生成接口。"""

    async def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """生成 JSON 对象。"""
        ...


class AgentFunctionCall(BaseModel):
    """OpenAI-compatible Tool Calling 中的函数调用。"""

    model_config = ConfigDict(extra="ignore")

    name: str
    arguments: str = "{}"


class AgentToolCall(BaseModel):
    """模型返回的一次工具调用。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    type: Literal["function"] = "function"
    function: AgentFunctionCall


class AgentAssistantMessage(BaseModel):
    """Agent 循环需要的最小 assistant 消息结构。"""

    model_config = ConfigDict(extra="ignore")

    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[AgentToolCall] = Field(default_factory=list)


class ToolCallingModel(Protocol):
    """Job Agent 依赖的最小 Tool Calling 模型接口。"""

    async def generate_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        require_tool: bool,
    ) -> AgentAssistantMessage:
        """根据对话和工具定义生成工具调用或最终回复。"""
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
    """调用 Qwen、DeepSeek 或 GLM 的 OpenAI-compatible Chat Completions API。"""

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

    @property
    def provider(self) -> LLMProvider:
        """返回当前请求实际选择的供应商，便于诊断和测试路由。"""
        return self._provider

    @property
    def model(self) -> str:
        """返回当前请求实际使用的模型编码。"""
        return self._model

    @property
    def is_configured(self) -> bool:
        """仅暴露是否已配置，不向调用方泄露 API Key。"""
        return self._api_key is not None

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
        elif self._provider in {"deepseek", "glm"}:
            # 结构化输出不需要推理内容；关闭思考也避免 Tool Calling 后续轮次
            # 被供应商要求回传 reasoning_content。
            request_body["thinking"] = {"type": "disabled"}

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

    async def generate_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        require_tool: bool,
    ) -> AgentAssistantMessage:
        """调用兼容接口的 Tool Calling 模式，返回标准化 assistant 消息。"""
        if not self._api_key:
            raise LLMConfigurationError("LLM API key is not configured")

        request_body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.1,
        }
        if tools:
            request_body["tools"] = tools
            if require_tool:
                # 两家兼容接口都支持具名工具选择；Graph 每轮只开放一个工具。
                request_body["tool_choice"] = {
                    "type": "function",
                    "function": {"name": tools[0]["function"]["name"]},
                }
            else:
                request_body["tool_choice"] = "auto"
        if self._provider == "qwen":
            # Qwen Tool Calling 使用非思考模式，避免 reasoning 内容干扰工具参数。
            request_body["enable_thinking"] = False
        elif self._provider in {"deepseek", "glm"}:
            request_body["thinking"] = {"type": "disabled"}

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
            logger.warning("LLM Tool Calling 请求失败 status_code=%s", exc.response.status_code)
            raise LLMClientError("LLM request failed") from exc
        except httpx.HTTPError as exc:
            logger.warning("LLM Tool Calling 网络失败 error_type=%s", type(exc).__name__)
            raise LLMClientError("LLM request failed") from exc

        try:
            message = response.json()["choices"][0]["message"]
            return AgentAssistantMessage.model_validate(message)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("LLM returned an invalid tool-calling response") from exc
