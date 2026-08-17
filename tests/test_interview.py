"""阶段 10 无限轮次自适应面试测试。"""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx

import app.models  # noqa: F401  # 注册面试表到 SQLAlchemy Metadata。
from app.agents.interview_agent import InterviewAgent
from app.api.interview import get_interview_agent
from app.db.base import Base
from app.main import app
from app.schemas.interview import InterviewAnswerRequest, InterviewStartRequest
from app.schemas.resume import ResumeParseResult
from app.services.interview_evaluator import InterviewEvaluator
from app.services.interview_service import InterviewService

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
            "name": "优惠券秒杀系统",
            "role": "后端开发",
            "description": "使用 Redis 实现优惠券秒杀功能。",
            "technologies": ["Java", "Redis"],
            "start_date": None,
            "end_date": None,
        }
    ],
    "internships": [],
    "certificates": [],
}
PROFILE_DATA = {
    "skills": {"Java": "advanced", "Redis": "advanced"},
    "domains": ["高并发"],
}
JOB_DATA = {
    "job_title": "Java后端实习生",
    "required_skills": ["Java", "Redis", "Kafka"],
    "preferred_skills": ["RabbitMQ"],
    "education": "本科及以上",
    "experience": None,
}


class StubInterviewLLM:
    """模拟简历首问、错误评价、追问和 JD 新题。"""

    async def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = json.loads(user_prompt)
        if "评价用户" in system_prompt:
            if payload["user_answer"] == "错误答案":
                return {
                    "score": 25,
                    "quality": "incorrect",
                    "errors": ["Redis 不能保证数据库事务原子性"],
                    "improvements": ["说明缓存与数据库一致性的处理策略"],
                    "weak_points": ["缓存一致性"],
                    "correct_answer": "应结合数据库事务、缓存失效策略和补偿机制处理。",
                }
            return {
                "score": 90,
                "quality": "mastered",
                "errors": [],
                "improvements": ["可以补充异常场景"],
                "weak_points": [],
                "correct_answer": "采用延迟双删或可靠消息，并处理失败补偿。",
            }

        source = payload["source"]
        if source == "resume":
            assert payload["resume"]["projects"][0]["name"] == "优惠券秒杀系统"
            return {
                "topic": "Redis 秒杀",
                "question": "你在优惠券秒杀项目中为什么使用 Redis？",
                "focus_points": ["性能", "并发控制"],
                "source_basis": "简历中的优惠券秒杀系统",
            }
        if source == "follow_up":
            previous = payload["previous_round"]
            assert previous["evaluation"]["user_answer"] == "错误答案"
            assert previous["evaluation"]["errors"]
            return {
                "topic": "缓存一致性",
                "question": "数据库更新成功但缓存删除失败时，你会如何处理？",
                "focus_points": ["重试", "补偿"],
                "source_basis": "上一轮回答暴露的缓存一致性问题",
            }
        if source == "requested":
            assert payload["requested_topic"].casefold() == "redis"
            return {
                "topic": "Redis",
                "question": "Redis 的 RDB 和 AOF 分别适合什么场景？",
                "focus_points": ["持久化机制", "恢复速度", "数据完整性"],
                "source_basis": "用户指定 Redis 主题",
            }
        assert "Kafka" in payload["parsed_job"]["required_skills"]
        return {
            "topic": "Kafka",
            "question": "Kafka 如何保证消息尽量不丢失？",
            "focus_points": ["acks", "重试", "位点提交"],
            "source_basis": "JD 要求掌握 Kafka",
        }


class FakeUserRepository:
    """仅返回当前测试用户。"""

    async def get_by_id(self, user_id: int) -> Any:
        return SimpleNamespace(id=1) if user_id == 1 else None


class FakeJobRepository:
    """返回已保存的原始 JD 和结构化岗位。"""

    async def get_by_id(self, job_id: int, *, user_id: int) -> Any:
        if (job_id, user_id) != (30, 1):
            return None
        return SimpleNamespace(
            id=30,
            user_id=1,
            raw_text="Java 实习岗位，要求 Java、Redis、Kafka。",
            parsed_data=JOB_DATA,
        )


class FakeProfileRepository:
    """固定本场面试使用的 Profile 和 Resume。"""

    record = SimpleNamespace(
        id=20,
        user_id=1,
        resume_id=10,
        profile_data=PROFILE_DATA,
    )

    async def get_current(self, user_id: int) -> Any:
        return self.record if user_id == 1 else None

    async def get_by_id(self, profile_id: int, *, user_id: int) -> Any:
        return self.record if (profile_id, user_id) == (20, 1) else None


class FakeResumeRepository:
    """返回本场面试绑定的结构化简历。"""

    async def get_by_id(self, resume_id: int, *, user_id: int) -> Any:
        if (resume_id, user_id) != (10, 1):
            return None
        return SimpleNamespace(
            id=10,
            user_id=1,
            storage_bucket="jobpilot-resumes",
            storage_object_key="users/1/resumes/test.pdf",
        )


class FakeResumeContentService:
    """从 MinIO 读取结构化简历的测试替身。"""

    async def load(self, _: Any) -> ResumeParseResult:
        return ResumeParseResult.model_validate(RESUME_DATA)


class FakeInterviewRepository:
    """内存保存每一轮题目、回答、评价和正确答案。"""

    def __init__(self) -> None:
        self.record: Any = None

    async def create(self, **values: Any) -> Any:
        self.record = SimpleNamespace(
            id=50,
            weak_points=[],
            created_at=NOW,
            updated_at=NOW,
            **values,
        )
        return self.record

    async def get_by_id(
        self,
        session_id: int,
        *,
        user_id: int,
        for_update: bool = False,
    ) -> Any:
        del for_update
        if self.record and (session_id, user_id) == (self.record.id, self.record.user_id):
            return self.record
        return None

    async def update_progress(self, record: Any, **values: Any) -> Any:
        for key, value in values.items():
            setattr(record, key, value)
        record.updated_at = NOW
        return record


def build_service() -> InterviewService:
    """组装不连接真实数据库和外部 LLM 的面试服务。"""
    llm = StubInterviewLLM()
    return InterviewService(
        llm_client=llm,
        evaluator=InterviewEvaluator(llm),
        interview_repository=FakeInterviewRepository(),  # type: ignore[arg-type]
        job_repository=FakeJobRepository(),  # type: ignore[arg-type]
        profile_repository=FakeProfileRepository(),  # type: ignore[arg-type]
        resume_repository=FakeResumeRepository(),  # type: ignore[arg-type]
        user_repository=FakeUserRepository(),  # type: ignore[arg-type]
        resume_content_service=FakeResumeContentService(),  # type: ignore[arg-type]
    )


def test_interview_adapts_without_question_limit_and_persists_answers() -> None:
    """错误时追问，掌握后转向 JD，并且不存在题数终止条件。"""

    async def run() -> None:
        service = build_service()
        session = await service.start(user_id=1, request=InterviewStartRequest(job_id=30))
        assert session.current_question is not None
        assert session.current_question.source == "resume"

        first = await service.answer(
            user_id=1,
            session_id=session.id,
            request=InterviewAnswerRequest(question_id="q1", answer="错误答案"),
        )
        assert first.evaluation.quality == "incorrect"
        assert first.evaluation.errors
        assert first.evaluation.correct_answer
        assert first.next_question.source == "follow_up"

        second = await service.answer(
            user_id=1,
            session_id=session.id,
            request=InterviewAnswerRequest(question_id="q2", answer="完善答案"),
        )
        assert second.evaluation.quality == "mastered"
        assert second.next_question.source == "jd"
        assert len(second.session.rounds) == 3
        assert second.session.rounds[0].evaluation is not None
        assert second.session.rounds[0].evaluation.user_answer == "错误答案"
        assert second.session.rounds[0].evaluation.correct_answer

    asyncio.run(run())


def test_interview_topic_command_replaces_pending_question_without_scoring() -> None:
    """指定 Redis 主题应替换待答题，不能生成一条 0 分评价。"""

    async def run() -> None:
        service = build_service()
        session = await service.start(user_id=1, request=InterviewStartRequest(job_id=30))

        question = await service.request_topic(
            user_id=1,
            session_id=session.id,
            topic="Redis",
        )
        updated = await service.get_session(user_id=1, session_id=session.id)

        assert question.question_id == "q1"
        assert question.source == "requested"
        assert question.topic == "Redis"
        assert len(updated.rounds) == 1
        assert updated.rounds[0].evaluation is None
        assert updated.current_question == question

    asyncio.run(run())


def test_topic_retry_removes_previously_misclassified_score() -> None:
    """旧前端已把主题指令评分时，重试换题应撤销错误轮次和衍生题。"""

    async def run() -> None:
        service = build_service()
        session = await service.start(user_id=1, request=InterviewStartRequest(job_id=30))
        mistaken = await service.answer(
            user_id=1,
            session_id=session.id,
            request=InterviewAnswerRequest(
                question_id="q1",
                answer="我想让你提问关于redis的",
            ),
        )
        assert mistaken.session.rounds[0].evaluation is not None

        question = await service.request_topic(
            user_id=1,
            session_id=session.id,
            topic="redis",
        )
        repaired = await service.get_session(user_id=1, session_id=session.id)

        assert question.question_id == "q1"
        assert len(repaired.rounds) == 1
        assert repaired.rounds[0].evaluation is None
        assert repaired.average_score is None
        assert repaired.weak_points == []

    asyncio.run(run())


def test_interview_routes_and_start_endpoint() -> None:
    """Swagger 应暴露启动、持续回答和汇总查询接口。"""
    assert "interview_sessions" in Base.metadata.tables
    paths = app.openapi()["paths"]
    assert "/users/{user_id}/interviews" in paths
    assert "/users/{user_id}/interviews/{interview_id}/answers" in paths
    assert "/users/{user_id}/interviews/{interview_id}" in paths

    agent = InterviewAgent(user_id=1, service=build_service())

    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/users/1/interviews", json={"job_id": 30})

    app.dependency_overrides[get_interview_agent] = lambda: agent
    try:
        response = asyncio.run(run())
    finally:
        app.dependency_overrides.pop(get_interview_agent, None)
    assert response.status_code == 201
    assert response.json()["data"]["current_question"]["source"] == "resume"
