"""Resume Agent Tool 路由和事实白名单测试。"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.agents.resume_agent import ResumeAgent
from app.schemas.resume import ResumeParseResult
from app.schemas.resume_agent import ResumeAgentAction, ResumeOptimizationSuggestion
from app.services.resume_optimization_service import ResumeOptimizationService

NOW = datetime(2026, 8, 12, tzinfo=UTC)
RESUME_DATA = {
    "personal_info": {
        "name": "张三",
        "email": None,
        "phone": None,
        "location": None,
    },
    "education": [],
    "skills": ["Java", "Redis"],
    "projects": [
        {
            "name": "秒杀系统",
            "role": None,
            "description": "使用 Redis 实现优惠券秒杀功能。",
            "technologies": ["Java", "Redis"],
            "start_date": None,
            "end_date": None,
        }
    ],
    "internships": [],
    "certificates": [],
}


class StubResumeService:
    """返回固定结构化 Resume。"""

    async def get(self, *, user_id: int, resume_id: int | None = None) -> Any:
        assert user_id == 1
        assert resume_id in (None, 10)
        return type(
            "ResumeRecordStub",
            (),
            {
                "model_dump": lambda self, mode: {
                    "id": 10,
                    "user_id": 1,
                    "filename": "resume.pdf",
                    "resume": RESUME_DATA,
                    "created_at": NOW.isoformat(),
                }
            },
        )()


class StubProfileService:
    """支持读取和重建 Profile。"""

    async def get_current(self, user_id: int) -> Any:
        assert user_id == 1
        return type(
            "ProfileRecordStub",
            (),
            {
                "model_dump": lambda self, mode: {
                    "id": 20,
                    "user_id": 1,
                    "resume_id": 10,
                    "profile": {
                        "skills": {"Java": "advanced", "Redis": "advanced"},
                        "domains": ["高并发"],
                    },
                    "is_current": True,
                    "created_at": NOW.isoformat(),
                }
            },
        )()

    async def build_and_save(self, *, user_id: int, resume_id: int) -> Any:
        assert (user_id, resume_id) == (1, 10)
        return await self.get_current(user_id)


class StubOptimizationService:
    """返回最小优化结果，验证 Agent 只负责 Tool 路由。"""

    async def optimize(self, *, user_id: int, resume_id: int | None, job_id: int) -> Any:
        assert (user_id, resume_id, job_id) == (1, 10, 30)
        return type(
            "OptimizationStub",
            (),
            {
                "model_dump": lambda self, mode: {
                    "resume_id": 10,
                    "profile_id": 20,
                    "job_id": 30,
                    "project_analysis": [],
                    "issues": [],
                    "suggestions": [],
                    "limitation": "仅基于结构化简历",
                }
            },
        )()


def build_resume_agent() -> ResumeAgent:
    """组装完全使用 Stub 的 Resume Agent。"""
    return ResumeAgent(
        user_id=1,
        resume_service=StubResumeService(),  # type: ignore[arg-type]
        profile_service=StubProfileService(),  # type: ignore[arg-type]
        optimization_service=StubOptimizationService(),  # type: ignore[arg-type]
    )


def test_resume_agent_routes_profile_and_optimization_tools() -> None:
    """Resume Agent 应为不同动作调用唯一对应 Tool。"""

    async def run() -> None:
        agent = build_resume_agent()
        profile = await agent.execute(action=ResumeAgentAction.GET_PROFILE, payload={})
        assert profile.tool_trace == ["get_profile"]
        assert profile.result["id"] == 20

        optimization = await agent.execute(
            action=ResumeAgentAction.OPTIMIZE_RESUME,
            payload={"resume_id": 10, "job_id": 30},
        )
        assert optimization.tool_trace == ["optimize_resume"]
        assert optimization.result["job_id"] == 30

    asyncio.run(run())


def test_resume_optimization_filters_unsupported_original_text() -> None:
    """Python 白名单必须过滤无法对应结构化简历原文的建议。"""
    resume = ResumeParseResult.model_validate(RESUME_DATA)
    valid = ResumeOptimizationSuggestion(
        section="projects",
        location="projects[0].description",
        original_text="使用 Redis 实现优惠券秒杀功能。",
        suggested_text="在秒杀项目中使用 Redis 支撑高并发访问。",
        reason="突出已有场景",
        jd_keywords=["Redis"],
    )
    fabricated = valid.model_copy(
        update={
            "location": "projects[1].description",
            "original_text": "使用 Kafka 异步下单。",
        }
    )

    accepted, rejected = ResumeOptimizationService._filter_supported_suggestions(
        resume=resume,
        suggestions=[valid, fabricated],
    )

    assert accepted == [valid]
    assert rejected == ["projects[1].description"]
