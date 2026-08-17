"""阶段 6 单 Job Agent 测试，不连接真实 LLM 或 MySQL。"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.agents.job_agent import JobAgent
from app.llm.client import AgentAssistantMessage, LLMProvider, OpenAICompatibleClient
from app.main import app
from app.schemas.agent import ConversationMessage, JobAgentRequest, JobAgentSessionRequest
from app.schemas.persistence import AnalysisDraft, AnalysisRecord, JobRecord, ProfileRecord

CREATED_AT = datetime(2026, 8, 12, tzinfo=UTC)

PROFILE_DATA = {
    "skills": {"Java": "advanced", "Redis": "intermediate"},
    "domains": ["后端开发"],
}
JOB_DATA = {
    "job_title": "Java后端工程师",
    "required_skills": ["Java", "Spring Boot", "MySQL", "Redis"],
    "preferred_skills": ["Kafka"],
    "education": "本科及以上",
    "experience": None,
}
MATCH_DATA = {
    "match_score": 82,
    "matched_skills": ["Java", "Redis"],
    "missing_skills": ["Spring Boot", "MySQL"],
    "strong_points": ["Java 能力较强"],
    "weak_points": ["缺少 Spring Boot 证据"],
    "recommendation": "RECOMMEND",
}


class StubToolCallingModel:
    """严格按 Graph 当前开放的唯一工具生成 Tool Call。"""

    def __init__(self) -> None:
        self.called_tools: list[str] = []
        self.last_messages: list[dict[str, Any]] = []

    async def generate_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        require_tool: bool,
    ) -> AgentAssistantMessage:
        assert messages[0]["role"] == "system"
        self.last_messages = messages
        previous_tool_calls = [
            message
            for message in messages
            if message["role"] == "assistant" and message.get("tool_calls")
        ]
        for message in previous_tool_calls:
            assert "content" in message
        if tools:
            assert require_tool is True
            tool_name = tools[0]["function"]["name"]
            self.called_tools.append(tool_name)
            return AgentAssistantMessage.model_validate(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call-{len(self.called_tools)}",
                            "type": "function",
                            "function": {"name": tool_name, "arguments": "{}"},
                        }
                    ],
                }
            )
        assert require_tool is False
        return AgentAssistantMessage(
            content="匹配分数 82，建议投递；Java 是优势，应补充 Spring Boot 和 MySQL 证据。"
        )


class StubProfileService:
    """返回已经保存的当前 Profile。"""

    async def get_current(self, user_id: int) -> ProfileRecord:
        assert user_id == 1
        return ProfileRecord(
            id=20,
            user_id=1,
            resume_id=10,
            profile=PROFILE_DATA,
            is_current=True,
            created_at=CREATED_AT,
        )


class StubJobService:
    """模拟调用 JDParserService 后保存岗位。"""

    async def parse_and_save(self, *, user_id: int, jd_text: str) -> JobRecord:
        assert user_id == 1
        assert "Java" in jd_text
        return JobRecord(
            id=30,
            user_id=1,
            raw_text=jd_text,
            job=JOB_DATA,
            created_at=CREATED_AT,
        )


class StubAnalysisService:
    """分别记录计算与保存，验证两个 Tool 没有合并职责。"""

    def __init__(self) -> None:
        self.calculate_count = 0
        self.save_count = 0

    async def calculate(self, *, user_id: int, job_id: int) -> AnalysisDraft:
        assert (user_id, job_id) == (1, 30)
        self.calculate_count += 1
        return AnalysisDraft(
            user_id=1,
            resume_id=10,
            profile_id=20,
            job_id=30,
            result=MATCH_DATA,
        )

    async def save(self, draft: AnalysisDraft) -> AnalysisRecord:
        assert draft.result.match_score == 82
        self.save_count += 1
        return AnalysisRecord(
            id=40,
            user_id=draft.user_id,
            resume_id=draft.resume_id,
            profile_id=draft.profile_id,
            job_id=draft.job_id,
            result=draft.result,
            created_at=CREATED_AT,
        )


def test_job_agent_route_is_registered() -> None:
    """OpenAPI 应暴露阶段 6 单 Agent 接口。"""
    assert "/users/{user_id}/agents/job/analyze" in app.openapi()["paths"]


@pytest.mark.parametrize(
    ("provider", "thinking_option"),
    [
        ("qwen", ("enable_thinking", False)),
        ("deepseek", ("thinking", {"type": "disabled"})),
        ("glm", ("thinking", {"type": "disabled"})),
    ],
)
def test_tool_calling_client_forces_named_tool(
    provider: LLMProvider,
    thinking_option: tuple[str, Any],
) -> None:
    """兼容客户端应使用三家供应商都支持的具名 Tool Choice。"""
    captured_body: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_candidate_profile",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    client = OpenAICompatibleClient(
        provider=provider,
        api_key="test-key",
        base_url="https://example.com/compatible-mode/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    tool_definition = {
        "type": "function",
        "function": {
            "name": "get_candidate_profile",
            "description": "查询当前 Profile",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    response = asyncio.run(
        client.generate_with_tools(
            messages=[{"role": "user", "content": "分析岗位"}],
            tools=[tool_definition],
            require_tool=True,
        )
    )

    assert response.tool_calls[0].function.name == "get_candidate_profile"
    assert captured_body["tools"] == [tool_definition]
    assert captured_body["tool_choice"] == {
        "type": "function",
        "function": {"name": "get_candidate_profile"},
    }
    option_name, option_value = thinking_option
    assert captured_body[option_name] == option_value


def test_job_agent_completes_tool_calling_workflow() -> None:
    """Agent 应按状态依次调用四个 Tool，再生成最终回答。"""
    model = StubToolCallingModel()
    analysis_service = StubAnalysisService()
    agent = JobAgent(
        model=model,
        user_id=1,
        profile_service=StubProfileService(),  # type: ignore[arg-type]
        job_service=StubJobService(),  # type: ignore[arg-type]
        analysis_service=analysis_service,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        agent.analyze(
            JobAgentRequest(jd_text="Java后端工程师，要求熟悉 Java、Spring Boot、MySQL 和 Redis。")
        )
    )

    assert result.tool_trace == [
        "get_candidate_profile",
        "parse_job_description",
        "calculate_job_match",
        "save_analysis",
    ]
    assert model.called_tools == result.tool_trace
    assert analysis_service.calculate_count == 1
    assert analysis_service.save_count == 1
    assert result.analysis.id == 40
    assert result.analysis.result.match_score == 82
    assert "建议投递" in result.final_answer


def test_job_agent_follow_up_uses_history_without_tools() -> None:
    """没有新 JD 的追问应直接使用会话上下文，不重复解析和保存。"""
    model = StubToolCallingModel()
    analysis_service = StubAnalysisService()
    agent = JobAgent(
        model=model,
        user_id=1,
        profile_service=StubProfileService(),  # type: ignore[arg-type]
        job_service=StubJobService(),  # type: ignore[arg-type]
        analysis_service=analysis_service,  # type: ignore[arg-type]
    )
    result = asyncio.run(
        agent.chat(
            JobAgentSessionRequest(
                session_id="session-001",
                message="那和刚才那个比呢？",
            ),
            turn=2,
            history=[
                ConversationMessage(
                    role="user",
                    content="这个岗位怎么样？",
                    created_at=CREATED_AT,
                ),
                ConversationMessage(
                    role="assistant",
                    content="建议投递。",
                    created_at=CREATED_AT,
                ),
            ],
            analysis_context=[{"job_title": "Java后端工程师", "match_score": 82}],
        )
    )

    assert model.called_tools == []
    assert result.tool_trace == []
    assert result.analysis is None
    assert result.job is None
    assert "Java后端工程师" in model.last_messages[0]["content"]
