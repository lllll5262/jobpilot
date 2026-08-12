"""阶段 8 多岗位对比、技能差距与 Agent Tool 测试。"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.agents.job_agent import JobAgent
from app.api.agent import get_comparison_job_agent
from app.llm.client import AgentAssistantMessage
from app.main import app
from app.schemas.comparison import (
    ComparisonJobSource,
    ComparisonSemanticAssessment,
    JobComparisonRequest,
    JobComparisonResult,
)
from app.schemas.persistence import AnalysisDraft, JobRecord, ProfileRecord
from app.schemas.profile import CandidateProfile
from app.services.gap_analysis_service import GapAnalysisService
from app.services.job_compare_service import JobCompareService

CREATED_AT = datetime(2026, 8, 12, tzinfo=UTC)

PROFILE_DATA = {
    "skills": {"Java": "advanced", "Redis": "advanced"},
    "domains": ["微服务", "高并发"],
}
BYTE_JOB = {
    "job_title": "Java后端实习生",
    "required_skills": ["Java", "Kafka", "Kubernetes"],
    "preferred_skills": [],
    "education": "本科及以上",
    "experience": None,
}
MEITUAN_JOB = {
    "job_title": "Java后端实习生",
    "required_skills": ["Java", "Redis", "Kafka"],
    "preferred_skills": [],
    "education": "本科及以上",
    "experience": None,
}


def make_job(job_id: int, data: dict[str, Any]) -> JobRecord:
    """构造一个已保存历史 JD。"""
    return JobRecord(
        id=job_id,
        user_id=1,
        raw_text=data["job_title"],
        job=data,
        created_at=CREATED_AT,
    )


def make_draft(job_id: int, score: int, missing_skills: list[str]) -> AnalysisDraft:
    """构造由规则引擎产生的分析草稿。"""
    return AnalysisDraft.model_validate(
        {
            "user_id": 1,
            "resume_id": 10,
            "profile_id": 20,
            "job_id": job_id,
            "result": {
                "match_score": score,
                "matched_skills": ["Java", "Redis"],
                "missing_skills": missing_skills,
                "strong_points": ["Java 与微服务经验匹配"],
                "weak_points": [f"缺少 {skill}" for skill in missing_skills],
                "recommendation": "RECOMMEND" if score >= 80 else "CONSIDER",
            },
        }
    )


class StubJobStorageService:
    """支持一个历史 JD 和一个新粘贴 JD。"""

    def __init__(self) -> None:
        self.history = make_job(101, BYTE_JOB)
        self.saved_texts: list[str] = []

    async def get_many(self, *, user_id: int, job_ids: list[int]) -> list[JobRecord]:
        assert user_id == 1
        assert job_ids == [101]
        return [self.history]

    async def parse_and_save(self, *, user_id: int, jd_text: str) -> JobRecord:
        assert user_id == 1
        self.saved_texts.append(jd_text)
        return make_job(102, MEITUAN_JOB)


class StubAnalysisStorageService:
    """返回 Python 规则引擎已经确定的两个分数。"""

    async def calculate_many(
        self,
        *,
        user_id: int,
        job_ids: list[int],
    ) -> list[AnalysisDraft]:
        assert user_id == 1
        assert job_ids == [101, 102]
        return [
            make_draft(101, 78, ["Kafka", "Kubernetes"]),
            make_draft(102, 86, ["Kafka"]),
        ]


class StubGapAnalysisService:
    """只提供文字分析，不返回任何分数字段。"""

    async def analyze(
        self,
        *,
        profile: CandidateProfile,
        jobs: list[dict[str, object]],
        recommended_job_id: int,
    ) -> ComparisonSemanticAssessment:
        assert "Redis" in profile.skills
        assert [job["job_id"] for job in jobs] == [102, 101]
        assert recommended_job_id == 102
        return ComparisonSemanticAssessment.model_validate(
            {
                "job_insights": [
                    {
                        "job_id": 102,
                        "advantages": ["Redis 项目经验直接匹配"],
                        "disadvantages": ["仍缺少 Kafka 证据"],
                        "skill_gap_actions": ["补充 Kafka 消息链路项目"],
                    },
                    {
                        "job_id": 101,
                        "advantages": ["Java 基础匹配"],
                        "disadvantages": ["基础设施技能缺口更多"],
                        "skill_gap_actions": ["学习 Kafka 和 Kubernetes"],
                    },
                ],
                "recommendation_reason": "美团岗位与你现有微服务和 Redis 项目经历更加匹配",
            }
        )


class StubGapJSONGenerator:
    """模拟差距分析 LLM 的 Structured Output。"""

    async def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        assert "不能修改分数、排名或推荐岗位" in system_prompt
        assert '"recommended_job_id": 102' in user_prompt
        return {
            "job_insights": [
                {
                    "job_id": 102,
                    "advantages": ["Redis 匹配"],
                    "disadvantages": ["缺少 Kafka"],
                    "skill_gap_actions": ["补充 Kafka 项目"],
                },
                {
                    "job_id": 101,
                    "advantages": ["Java 匹配"],
                    "disadvantages": ["缺少 Kubernetes"],
                    "skill_gap_actions": ["学习 Kubernetes"],
                },
            ],
            "recommendation_reason": "102 号岗位技能缺口更少",
        }


class StubProfileService:
    """返回当前 Candidate Profile。"""

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


class StubComparisonService:
    """为 Agent Graph 提供已经完成的结构化对比。"""

    async def compare(
        self,
        *,
        user_id: int,
        sources: list[ComparisonJobSource],
        profile: CandidateProfile,
    ) -> JobComparisonResult:
        assert user_id == 1
        assert [source.job_id for source in sources] == [101, 102]
        assert "Java" in profile.skills
        return JobComparisonResult.model_validate(
            {
                "recommended_job_id": 102,
                "recommended_job": "美团 Java后端实习生",
                "comparisons": [
                    {
                        "rank": 1,
                        "job_id": 102,
                        "job": "美团 Java后端实习生",
                        "score": 86,
                        "recommendation": "RECOMMEND",
                        "matched_skills": ["Java", "Redis"],
                        "missing_skills": ["Kafka"],
                        "strong_points": [],
                        "weak_points": [],
                        "advantages": ["Redis 匹配"],
                        "disadvantages": [],
                        "skill_gap_actions": ["补充 Kafka"],
                    },
                    {
                        "rank": 2,
                        "job_id": 101,
                        "job": "字节 Java后端实习生",
                        "score": 78,
                        "recommendation": "CONSIDER",
                        "matched_skills": ["Java"],
                        "missing_skills": ["Kafka", "Kubernetes"],
                        "strong_points": [],
                        "weak_points": [],
                        "advantages": ["Java 匹配"],
                        "disadvantages": ["技能缺口较多"],
                        "skill_gap_actions": ["补充基础设施项目"],
                    },
                ],
                "reason": "美团岗位与你现有 Redis 项目更加匹配",
            }
        )


class StubComparisonModel:
    """遵循 Graph 开放顺序调用 Profile 和 Compare Tool。"""

    def __init__(self) -> None:
        self.called_tools: list[str] = []

    async def generate_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        require_tool: bool,
    ) -> AgentAssistantMessage:
        del messages
        if tools:
            assert require_tool is True
            tool_name = tools[0]["function"]["name"]
            self.called_tools.append(tool_name)
            return AgentAssistantMessage.model_validate(
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call-{len(self.called_tools)}",
                            "function": {"name": tool_name, "arguments": "{}"},
                        }
                    ],
                }
            )
        return AgentAssistantMessage(content="美团岗位 86 分，更适合当前候选人。")


def test_comparison_request_accepts_history_and_pasted_jd() -> None:
    """同一请求可以混合历史岗位和新粘贴 JD。"""
    request = JobComparisonRequest(
        jobs=[
            {"job_id": 101, "label": "字节"},
            {"jd_text": "美团 Java 实习岗位，要求 Java、Redis、Kafka", "label": "美团"},
        ]
    )
    assert request.jobs[0].job_id == 101
    assert request.jobs[1].jd_text is not None

    with pytest.raises(ValidationError):
        JobComparisonRequest(jobs=[{"job_id": 101}, {"job_id": 101}])


def test_job_compare_service_uses_rule_score_for_ranking() -> None:
    """最终推荐必须服从规则分数，并合并 LLM 技能差距说明。"""
    async def run() -> None:
        job_service = StubJobStorageService()
        service = JobCompareService(
            job_service=job_service,  # type: ignore[arg-type]
            analysis_service=StubAnalysisStorageService(),  # type: ignore[arg-type]
            gap_analysis_service=StubGapAnalysisService(),  # type: ignore[arg-type]
        )
        result = await service.compare(
            user_id=1,
            sources=[
                ComparisonJobSource(job_id=101, label="字节"),
                ComparisonJobSource(jd_text="美团 Java、Redis、Kafka 岗位", label="美团"),
            ],
            profile=CandidateProfile.model_validate(PROFILE_DATA),
        )

        assert result.recommended_job_id == 102
        assert result.recommended_job == "美团 Java后端实习生"
        assert [item.score for item in result.comparisons] == [86, 78]
        assert result.comparisons[0].missing_skills == ["Kafka"]
        assert job_service.saved_texts == ["美团 Java、Redis、Kafka 岗位"]

    asyncio.run(run())


def test_gap_analysis_service_validates_structured_output() -> None:
    """差距分析必须经过 Pydantic 校验，并覆盖所有输入岗位。"""
    result = asyncio.run(
        GapAnalysisService(StubGapJSONGenerator()).analyze(
            profile=CandidateProfile.model_validate(PROFILE_DATA),
            jobs=[
                {"job_id": 102, "score": 86},
                {"job_id": 101, "score": 78},
            ],
            recommended_job_id=102,
        )
    )

    assert [item.job_id for item in result.job_insights] == [102, 101]
    assert result.recommendation_reason == "102 号岗位技能缺口更少"


def test_job_agent_runs_comparison_tool_workflow() -> None:
    """Agent 应先读取 Profile，再调用多岗位对比 Tool。"""
    model = StubComparisonModel()
    agent = JobAgent(
        model=model,
        user_id=1,
        profile_service=StubProfileService(),  # type: ignore[arg-type]
        job_service=object(),  # type: ignore[arg-type]
        analysis_service=object(),  # type: ignore[arg-type]
        job_compare_service=StubComparisonService(),  # type: ignore[arg-type]
    )
    result = asyncio.run(
        agent.compare(
            JobComparisonRequest(
                message="帮我比较字节和美团岗位",
                jobs=[
                    {"job_id": 101, "label": "字节"},
                    {"job_id": 102, "label": "美团"},
                ],
            )
        )
    )

    assert result.tool_trace == ["get_candidate_profile", "compare_jobs"]
    assert model.called_tools == result.tool_trace
    assert result.comparison.recommended_job_id == 102
    assert "更适合" in result.final_answer


def test_job_comparison_route_is_registered() -> None:
    """OpenAPI 应暴露阶段 8 多岗位对比接口。"""
    paths = app.openapi()["paths"]
    assert "/users/{user_id}/jobs" in paths
    assert "/users/{user_id}/agents/job/compare" in paths


def test_job_comparison_endpoint_returns_unified_response() -> None:
    """HTTP 接口应返回统一响应结构和结构化推荐结果。"""
    agent = JobAgent(
        model=StubComparisonModel(),
        user_id=1,
        profile_service=StubProfileService(),  # type: ignore[arg-type]
        job_service=object(),  # type: ignore[arg-type]
        analysis_service=object(),  # type: ignore[arg-type]
        job_compare_service=StubComparisonService(),  # type: ignore[arg-type]
    )

    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/users/1/agents/job/compare",
                json={
                    "message": "帮我比较字节和美团岗位",
                    "jobs": [
                        {"job_id": 101, "label": "字节"},
                        {"job_id": 102, "label": "美团"},
                    ],
                },
            )

    app.dependency_overrides[get_comparison_job_agent] = lambda: agent
    try:
        response = asyncio.run(run())
    finally:
        app.dependency_overrides.pop(get_comparison_job_agent, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["message"] == "success"
    assert payload["data"]["comparison"]["recommended_job_id"] == 102
