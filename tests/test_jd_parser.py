"""JD 解析功能测试。"""

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.api.job import get_jd_parser_service
from app.core.exceptions import AppException
from app.llm.client import LLMProvider, OpenAICompatibleClient
from app.main import app
from app.schemas.job import JDParseResult
from app.services.jd_parser_service import JDParserService

JD_TEXT = """Java后端实习生

要求：
熟悉 Java、Spring Boot、MySQL；
掌握 Redis；
Kafka 经验优先；
本科及以上。
"""

PARSED_JD = {
    "job_title": "Java后端实习生",
    "required_skills": ["Java", "Spring Boot", "MySQL", "Redis"],
    "preferred_skills": ["Kafka"],
    "education": "本科及以上",
    "experience": None,
}


class StubLLMClient:
    """返回固定结构的 LLM 测试替身。"""

    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result

    async def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        assert "JSON" in system_prompt
        assert JD_TEXT.strip() in user_prompt
        return self._result


class StubJDParserService:
    """隔离 API 层与真实 LLM 的测试服务。"""

    async def parse(self, jd_text: str) -> JDParseResult:
        assert jd_text == JD_TEXT.strip()
        return JDParseResult.model_validate(PARSED_JD)


async def _post(path: str, payload: dict[str, Any]) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.post(path, json=payload)


def test_jd_parser_service_validates_structured_output() -> None:
    """服务应将合法的 LLM JSON 转换为强类型结果。"""
    service = JDParserService(StubLLMClient(PARSED_JD))

    result = asyncio.run(service.parse(JD_TEXT))

    assert result == JDParseResult.model_validate(PARSED_JD)


def test_jd_parser_service_rejects_invalid_structured_output() -> None:
    """缺少必填字段的模型输出不能进入 API 响应。"""
    service = JDParserService(StubLLMClient({"job_title": "Java后端实习生"}))

    with pytest.raises(AppException) as exc_info:
        asyncio.run(service.parse(JD_TEXT))

    assert exc_info.value.code == 50202


@pytest.mark.parametrize(
    ("provider", "expects_thinking_option"),
    [("qwen", True), ("deepseek", False)],
)
def test_compatible_client_uses_provider_specific_json_mode(
    provider: LLMProvider,
    expects_thinking_option: bool,
) -> None:
    """两家供应商共用 JSON Mode，但只有 Qwen 需要关闭思考模式。"""
    captured_request: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_request["url"] = str(request.url)
        captured_request["authorization"] = request.headers["Authorization"]
        captured_request["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(PARSED_JD)}}]},
        )

    client = OpenAICompatibleClient(
        provider=provider,
        api_key="test-key",
        base_url="https://example.com/compatible-mode/v1",
        model="qwen-plus",
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(client.generate_json(system_prompt="输出 JSON", user_prompt="测试 JD"))

    assert result == PARSED_JD
    assert captured_request["url"].endswith("/compatible-mode/v1/chat/completions")
    assert captured_request["authorization"] == "Bearer test-key"
    assert captured_request["body"]["response_format"] == {"type": "json_object"}
    if expects_thinking_option:
        assert captured_request["body"]["enable_thinking"] is False
    else:
        assert "enable_thinking" not in captured_request["body"]


def test_parse_job_description_endpoint() -> None:
    """API 应返回阶段约定的统一响应结构。"""
    app.dependency_overrides[get_jd_parser_service] = StubJDParserService
    try:
        response = asyncio.run(_post("/jobs/parse", {"jd_text": JD_TEXT}))
    finally:
        app.dependency_overrides.pop(get_jd_parser_service, None)

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "success",
        "data": PARSED_JD,
    }


def test_parse_endpoint_returns_503_without_api_key() -> None:
    """缺少密钥时应快速失败，并保持统一错误响应。"""

    def build_unconfigured_service() -> JDParserService:
        client = OpenAICompatibleClient(
            provider="qwen",
            api_key=None,
            base_url="https://example.com/compatible-mode/v1",
            model="qwen-plus",
        )
        return JDParserService(client)

    app.dependency_overrides[get_jd_parser_service] = build_unconfigured_service
    try:
        response = asyncio.run(_post("/jobs/parse", {"jd_text": JD_TEXT}))
    finally:
        app.dependency_overrides.pop(get_jd_parser_service, None)

    assert response.status_code == 503
    assert response.json() == {
        "code": 50301,
        "message": "LLM is not configured",
        "data": None,
    }
