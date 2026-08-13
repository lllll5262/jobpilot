"""岗位匹配与规则引擎测试。"""

import asyncio
from typing import Any

import httpx
import pytest

from app.api.match import get_match_service
from app.main import app
from app.rules.education_rules import EducationFit, evaluate_education
from app.rules.skill_rules import evaluate_skills
from app.schemas.job import JDParseResult
from app.schemas.match import (
    ExperienceFit,
    MatchResult,
    ProjectRelevance,
    Recommendation,
    SemanticSkillMatch,
)
from app.schemas.profile import CandidateProfile
from app.schemas.resume import EducationExperience, ResumeParseResult
from app.services.match_service import MatchService
from app.services.scoring_service import ScoreInput, ScoringService

RESUME = {
    "personal_info": {
        "name": "张三",
        "email": None,
        "phone": None,
        "location": None,
    },
    "education": [
        {
            "school": "示例大学",
            "degree": "本科",
            "major": "计算机科学",
            "start_date": "2020",
            "end_date": "2024",
        }
    ],
    "skills": ["Java", "Redis", "RabbitMQ", "Kafka"],
    "projects": [
        {
            "name": "优惠券秒杀系统",
            "role": "后端开发",
            "description": "使用 Redis + Lua 实现优惠券秒杀和库存原子扣减。",
            "technologies": ["Java", "Redis", "Lua"],
            "start_date": None,
            "end_date": None,
        },
        {
            "name": "异步订单系统",
            "role": "后端开发",
            "description": "使用 RabbitMQ 异步创建订单并削峰。",
            "technologies": ["Java", "RabbitMQ"],
            "start_date": None,
            "end_date": None,
        },
    ],
    "internships": [],
    "certificates": [],
}

PROFILE = {
    "skills": {
        "Java": "advanced",
        "Redis": "advanced",
        "RabbitMQ": "intermediate",
        "Kafka": "unknown",
    },
    "domains": ["高并发", "异步处理"],
}

JOB = {
    "job_title": "Java后端工程师",
    "required_skills": ["Java", "Redis", "RabbitMQ"],
    "preferred_skills": ["Kafka"],
    "education": "本科及以上",
    "experience": "1-3年相关项目经验",
}

SEMANTIC_ASSESSMENT = {
    "semantic_skill_matches": [],
    "project_relevance": "high",
    "experience_fit": "partial",
    "strong_points": ["具备高并发秒杀和异步订单项目经验"],
    "weak_points": ["Kafka 仅列出但缺少项目证据"],
}


class StubLLMClient:
    """返回固定语义判断，但不返回任何数值分数。"""

    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        self.system_prompt: str | None = None

    async def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        assert "优惠券秒杀系统" in user_prompt
        assert "Java后端工程师" in user_prompt
        self.system_prompt = system_prompt
        return self._result


class StubMatchService:
    """隔离 API 层与真实语义分析的测试服务。"""

    async def match(
        self,
        *,
        resume: ResumeParseResult,
        profile: CandidateProfile,
        job: JDParseResult,
    ) -> MatchResult:
        assert resume.personal_info.name == "张三"
        assert profile.skills["Redis"] == "advanced"
        assert job.job_title == "Java后端工程师"
        return MatchResult(
            match_score=82,
            matched_skills=["Java", "Redis", "RabbitMQ"],
            missing_skills=[],
            strong_points=["具备相关项目经验"],
            weak_points=["Kafka 证据不足"],
            recommendation=Recommendation.RECOMMEND,
        )


async def _post(path: str, payload: dict[str, Any]) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.post(path, json=payload)


@pytest.mark.parametrize(
    ("requirement", "degree", "expected"),
    [
        ("本科及以上", "硕士", EducationFit.MEETS),
        ("硕士及以上", "本科", EducationFit.NOT_MEETS),
        (None, None, EducationFit.NOT_REQUIRED),
        ("学历面议", None, EducationFit.UNKNOWN),
    ],
)
def test_education_rules(
    requirement: str | None,
    degree: str | None,
    expected: EducationFit,
) -> None:
    """学历规则应支持等级比较、无要求和未知状态。"""
    education = [EducationExperience(school="示例大学", degree=degree)] if degree else []

    assert evaluate_education(requirement, education) == expected


def test_skill_rules_validate_semantic_matches() -> None:
    """LLM 技能映射只有两端存在于真实输入时才参与计算。"""
    result = evaluate_skills(
        required_skills=["Java", "Message Queue", "Kafka"],
        preferred_skills=["Redis"],
        candidate_skills=CandidateProfile.model_validate(
            {
                "skills": {
                    "Java": "advanced",
                    "RabbitMQ": "intermediate",
                    "Kafka": "unknown",
                    "Redis": "beginner",
                },
                "domains": [],
            }
        ).skills,
        semantic_matches=[
            SemanticSkillMatch(
                job_skill="Message Queue",
                candidate_skill="RabbitMQ",
                reason="RabbitMQ 是消息队列实现",
            ),
            SemanticSkillMatch(
                job_skill="Kafka",
                candidate_skill="不存在的技能",
                reason="该映射应被规则引擎拒绝",
            ),
        ],
    )

    assert result.required_ratio == pytest.approx(0.6)
    assert result.preferred_ratio == pytest.approx(0.5)
    assert result.matched_skills == ["Java", "Message Queue", "Redis"]
    assert result.missing_skills == ["Kafka"]


def test_scoring_service_calculates_82_without_llm_score() -> None:
    """固定权重应产生可复现的 82 分和推荐结论。"""
    result = ScoringService().calculate(
        ScoreInput(
            required_skill_ratio=0.8,
            preferred_skill_ratio=0.6,
            project_relevance=ProjectRelevance.HIGH,
            experience_fit=ExperienceFit.PARTIAL,
            education_fit=EducationFit.MEETS,
            experience_required=True,
        )
    )

    assert result.score == 82
    assert result.recommendation == Recommendation.RECOMMEND


def test_match_service_combines_semantics_and_rules() -> None:
    """完整服务只采用 LLM 语义判断，最终分数由 Python 计算。"""
    llm_client = StubLLMClient(SEMANTIC_ASSESSMENT)
    service = MatchService(llm_client, ScoringService())

    result = asyncio.run(
        service.match(
            resume=ResumeParseResult.model_validate(RESUME),
            profile=CandidateProfile.model_validate(PROFILE),
            job=JDParseResult.model_validate(JOB),
        )
    )

    assert result.match_score == 81
    assert result.recommendation == Recommendation.RECOMMEND
    assert result.matched_skills == ["Java", "Redis", "RabbitMQ"]
    assert result.missing_skills == []
    assert llm_client.system_prompt is not None
    assert "不得输出或暗示任何数字分数" in llm_client.system_prompt


def test_evaluate_match_endpoint() -> None:
    """API 应组合三个领域对象并保持统一响应结构。"""
    app.dependency_overrides[get_match_service] = StubMatchService
    try:
        response = asyncio.run(
            _post(
                "/matches/evaluate",
                {"resume": RESUME, "profile": PROFILE, "job": JOB},
            )
        )
    finally:
        app.dependency_overrides.pop(get_match_service, None)

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "success",
        "data": {
            "match_score": 82,
            "matched_skills": ["Java", "Redis", "RabbitMQ"],
            "missing_skills": [],
            "strong_points": ["具备相关项目经验"],
            "weak_points": ["Kafka 证据不足"],
            "recommendation": "RECOMMEND",
        },
    }
