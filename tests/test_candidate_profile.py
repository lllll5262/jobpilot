"""候选人能力画像功能测试。"""

import asyncio
from typing import Any

import httpx
import pytest

from app.api.profile import get_profile_service
from app.core.exceptions import AppException
from app.main import app
from app.schemas.profile import CandidateProfile
from app.schemas.resume import ResumeParseResult
from app.services.profile_service import CandidateProfileService

RESUME = {
    "personal_info": {
        "name": "张三",
        "email": None,
        "phone": None,
        "location": None,
    },
    "education": [],
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
    "domains": ["高并发", "异步消息"],
}


class StubLLMClient:
    """返回固定能力画像并记录输入的 LLM 测试替身。"""

    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        self.user_prompt: str | None = None

    async def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        assert "advanced" in system_prompt
        assert "unknown" in system_prompt
        self.user_prompt = user_prompt
        return self._result


class StubProfileService:
    """隔离 API 层与真实 LLM 的画像服务。"""

    async def build(self, resume: ResumeParseResult) -> CandidateProfile:
        assert "Redis" in resume.skills
        return CandidateProfile.model_validate(PROFILE)


async def _post(path: str, payload: dict[str, Any]) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.post(path, json=payload)


def test_profile_service_builds_profile_from_resume() -> None:
    """服务应从 Resume 构建经过 Schema 校验的独立 Profile。"""
    llm_client = StubLLMClient(PROFILE)
    service = CandidateProfileService(llm_client)

    result = asyncio.run(service.build(ResumeParseResult.model_validate(RESUME)))

    assert result == CandidateProfile.model_validate(PROFILE)
    assert llm_client.user_prompt is not None
    assert "优惠券秒杀系统" in llm_client.user_prompt
    assert "Redis + Lua" in llm_client.user_prompt


def test_profile_service_rejects_invalid_skill_level() -> None:
    """不在枚举中的技能等级不能进入接口响应。"""
    invalid_profile = {
        "skills": {"Java": "expert"},
        "domains": ["微服务"],
    }
    service = CandidateProfileService(StubLLMClient(invalid_profile))

    with pytest.raises(AppException) as exc_info:
        asyncio.run(service.build(ResumeParseResult.model_validate(RESUME)))

    assert exc_info.value.code == 50202


def test_candidate_profile_normalizes_duplicates() -> None:
    """画像 Schema 应清理技能和领域的空白与重复项。"""
    profile = CandidateProfile.model_validate(
        {
            "skills": {" Redis ": "advanced", "redis": "intermediate", "": "unknown"},
            "domains": [" 高并发 ", "高并发", ""],
        }
    )

    assert profile.model_dump(mode="json") == {
        "skills": {"Redis": "advanced"},
        "domains": ["高并发"],
    }


def test_build_candidate_profile_endpoint() -> None:
    """画像接口应保持统一响应结构，且不修改输入 Resume。"""
    app.dependency_overrides[get_profile_service] = StubProfileService
    try:
        response = asyncio.run(_post("/profiles/build", {"resume": RESUME}))
    finally:
        app.dependency_overrides.pop(get_profile_service, None)

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "success",
        "data": PROFILE,
    }
