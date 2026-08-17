"""Supervisor 路由、领域隔离和统一 API 测试。"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.supervisor import SupervisorAgent
from app.api.supervisor import get_supervisor_agent
from app.main import app
from app.schemas.agent import JobAgentResponse
from app.schemas.interview import InterviewAgentResult
from app.schemas.job import JDParseResult
from app.schemas.match import MatchResult
from app.schemas.persistence import AnalysisRecord, JobRecord
from app.schemas.resume_agent import ResumeAgentResult
from app.schemas.supervisor import SupervisorRequest

SESSION_ID = "supervisor-session-001"


class StubRouteModel:
    """根据消息返回严格受限的 Supervisor 路由。"""

    async def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        assert "不能解析简历" in system_prompt
        assert "job_id" not in user_prompt
        if "面试" in user_prompt:
            return {
                "target_agent": "interview",
                "action": "create_interview_plan",
                "reason": "用户希望开始面试",
            }
        return {
            "target_agent": "resume",
            "action": "get_profile",
            "reason": "用户希望查看画像",
        }


class StubResumeAgent:
    """记录 Supervisor 原样转交的 payload。"""

    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    async def execute(self, *, action: Any, payload: dict[str, Any]) -> ResumeAgentResult:
        self.payload = payload
        return ResumeAgentResult(
            action=action,
            result={"profile_id": 20},
            tool_trace=[action.value],
        )


class StubInterviewAgent:
    """模拟 Interview Agent 创建第一题。"""

    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    async def execute(self, *, action: Any, payload: dict[str, Any]) -> InterviewAgentResult:
        self.payload = payload
        return InterviewAgentResult(
            action=action.value,
            result={"interview_id": 50, "question_id": "q1"},
            tool_trace=[action.value],
        )


class StubJobAgent:
    """普通路由测试不应调用 Job Agent。"""

    async def analyze(self, request: Any) -> Any:
        raise AssertionError(f"unexpected job analysis: {request}")


class StubAnalyzingJobAgent:
    """返回完整岗位分析，验证纯 JD 的确定性路由。"""

    async def analyze(self, request: Any) -> JobAgentResponse:
        now = datetime.now(UTC)
        job = JobRecord(
            id=31,
            user_id=1,
            raw_text=request.jd_text,
            job=JDParseResult(
                job_title="Java 后端实习生",
                required_skills=["Java", "MySQL"],
                preferred_skills=["Redis"],
                education="本科",
                experience=None,
            ),
            created_at=now,
        )
        analysis = AnalysisRecord(
            id=41,
            user_id=1,
            resume_id=10,
            profile_id=20,
            job_id=31,
            result=MatchResult(
                match_score=80,
                matched_skills=["Java"],
                missing_skills=["MySQL"],
                strong_points=[],
                weak_points=[],
                recommendation="RECOMMEND",
            ),
            created_at=now,
        )
        return JobAgentResponse(
            final_answer="该岗位与你较匹配。",
            analysis=analysis,
            job=job,
            tool_trace=[
                "get_candidate_profile",
                "parse_job_description",
                "calculate_job_match",
                "save_analysis",
            ],
        )


def build_supervisor() -> tuple[SupervisorAgent, StubResumeAgent, StubInterviewAgent]:
    """组装不连接外部资源的 Supervisor。"""
    resume_agent = StubResumeAgent()
    interview_agent = StubInterviewAgent()
    supervisor = SupervisorAgent(
        model=StubRouteModel(),
        resume_agent=resume_agent,  # type: ignore[arg-type]
        job_agent=StubJobAgent(),  # type: ignore[arg-type]
        interview_agent=interview_agent,  # type: ignore[arg-type]
        user_id=1,
    )
    return supervisor, resume_agent, interview_agent


def test_supervisor_routes_and_preserves_trusted_payload() -> None:
    """Supervisor 只分类和转交，不能看到或改写 payload 中的业务 ID。"""
    supervisor, _, interview_agent = build_supervisor()
    payload = {"job_id": 30}
    result = asyncio.run(
        supervisor.handle(
            SupervisorRequest(
                session_id=SESSION_ID,
                message="根据我的简历开始模拟面试",
                payload=payload,
            )
        )
    )

    assert result.target_agent == "interview"
    assert result.action == "create_interview_plan"
    assert result.agent_trace == ["supervisor", "interview"]
    assert result.tool_trace == ["create_interview_plan"]
    assert interview_agent.payload == payload


def test_supervisor_drops_resume_id_before_interview_dispatch() -> None:
    """前端共享上下文中的 Resume ID 不应污染 Interview Agent 参数。"""
    supervisor, _, interview_agent = build_supervisor()
    result = asyncio.run(
        supervisor.handle(
            SupervisorRequest(
                session_id=SESSION_ID,
                message="根据我的简历开始模拟面试",
                payload={"job_id": 30, "resume_id": 3},
            )
        )
    )

    assert result.target_agent == "interview"
    assert result.action == "create_interview_plan"
    assert interview_agent.payload == {"job_id": 30}


def test_supervisor_endpoint_returns_unified_response() -> None:
    """统一入口应组合领域 Agent 结果并保留调用轨迹。"""
    supervisor, _, _ = build_supervisor()

    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/users/1/supervisor",
                json={
                    "session_id": SESSION_ID,
                    "message": "查看我的候选人画像",
                    "payload": {},
                },
            )

    app.dependency_overrides[get_supervisor_agent] = lambda: supervisor
    try:
        response = asyncio.run(run())
    finally:
        app.dependency_overrides.pop(get_supervisor_agent, None)

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["target_agent"] == "resume"
    assert body["data"]["result"] == {"profile_id": 20}


def test_supervisor_answers_identity_without_calling_domain_agent() -> None:
    """“你是谁”必须由 Supervisor 直接回答，不能读取候选人画像。"""
    supervisor, resume_agent, _ = build_supervisor()
    result = asyncio.run(
        supervisor.handle(
            SupervisorRequest(session_id=SESSION_ID, message="你是谁", payload={})
        )
    )

    assert result.target_agent == "supervisor"
    assert result.action == "respond"
    assert "JobPilot" in result.result["message"]
    assert result.tool_trace == []
    assert resume_agent.payload is None


def test_supervisor_routes_resume_fact_question_to_rag_answer() -> None:
    """简历具体事实问题必须携带原问题进入 RAG，而不是返回整份简历摘要。"""
    supervisor, resume_agent, _ = build_supervisor()
    result = asyncio.run(
        supervisor.handle(
            SupervisorRequest(
                session_id=SESSION_ID,
                message="简历写的是那个学校",
                payload={"resume_id": 10},
            )
        )
    )

    assert result.target_agent == "resume"
    assert result.action == "answer_resume"
    assert result.tool_trace == ["answer_resume"]
    assert resume_agent.payload == {
        "resume_id": 10,
        "query": "简历写的是那个学校",
    }


def test_supervisor_treats_requested_interview_topic_as_command() -> None:
    """即使前端残留 answer 字段，指定主题也不得作为上一题答案评分。"""
    supervisor, _, interview_agent = build_supervisor()
    result = asyncio.run(
        supervisor.handle(
            SupervisorRequest(
                session_id=SESSION_ID,
                message="我想让你提问关于redis的",
                payload={
                    "interview_id": 50,
                    "question_id": "q1",
                    "answer": "我想让你提问关于redis的",
                },
            )
        )
    )

    assert result.target_agent == "interview"
    assert result.action == "request_topic"
    assert result.tool_trace == ["request_topic"]
    assert interview_agent.payload == {"interview_id": 50, "topic": "redis"}


def test_supervisor_detects_pasted_jd_without_explicit_instruction() -> None:
    """直接粘贴 JD 时应默认进入岗位匹配，不依赖用户说出“分析”。"""
    resume_agent = StubResumeAgent()
    interview_agent = StubInterviewAgent()
    supervisor = SupervisorAgent(
        model=StubRouteModel(),
        resume_agent=resume_agent,  # type: ignore[arg-type]
        job_agent=StubAnalyzingJobAgent(),  # type: ignore[arg-type]
        interview_agent=interview_agent,  # type: ignore[arg-type]
        user_id=1,
    )
    jd_text = (
        "Java 后端实习生\n岗位职责：负责订单系统开发与维护。\n"
        "任职要求：熟悉 Java 和 MySQL，掌握 Redis，本科及以上学历，有项目经验者优先。"
    )
    result = asyncio.run(
        supervisor.handle(
            SupervisorRequest(session_id=SESSION_ID, message=jd_text, payload={})
        )
    )

    assert result.target_agent == "job"
    assert result.action == "analyze_job"
    assert result.result["job"]["id"] == 31
    assert result.result["analysis"]["result"]["match_score"] == 80


def test_supervisor_saves_checkpoint_with_stable_session_thread() -> None:
    """同一 session_id 应写入可恢复的 Supervisor LangGraph Checkpoint。"""

    async def run() -> None:
        saver = InMemorySaver()
        resume_agent = StubResumeAgent()
        supervisor = SupervisorAgent(
            model=StubRouteModel(),
            resume_agent=resume_agent,  # type: ignore[arg-type]
            job_agent=StubJobAgent(),  # type: ignore[arg-type]
            interview_agent=StubInterviewAgent(),  # type: ignore[arg-type]
            user_id=1,
            checkpointer=saver,
        )
        await supervisor.handle(
            SupervisorRequest(
                session_id=SESSION_ID,
                message="查看我的候选人画像",
                payload={},
            )
        )

        checkpoint = await saver.aget_tuple(
            {
                "configurable": {
                    "thread_id": f"supervisor:user:1:session:{SESSION_ID}",
                }
            }
        )

        assert checkpoint is not None
        state = checkpoint.checkpoint["channel_values"]
        assert state["user_id"] == 1
        assert state["session_id"] == SESSION_ID
        assert state["final_result"]["target_agent"] == "resume"

    asyncio.run(run())
