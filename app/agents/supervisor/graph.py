"""Supervisor 路由、委派和结果组合 Graph。"""

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.interview_agent import InterviewAgent
from app.agents.job_agent import JobAgent
from app.agents.resume_agent import ResumeAgent
from app.agents.supervisor.prompt import (
    build_supervisor_system_prompt,
    build_supervisor_user_prompt,
)
from app.agents.supervisor.state import SupervisorState
from app.core.exceptions import AppException
from app.llm.client import JSONGenerator
from app.schemas.agent import JobAgentRequest
from app.schemas.interview import InterviewAgentAction
from app.schemas.resume_agent import ResumeAgentAction
from app.schemas.supervisor import (
    AgentTarget,
    JobSupervisorAction,
    SupervisorAction,
    SupervisorResponse,
    SupervisorRoute,
)
from app.services.structured_output import generate_structured_output


class SupervisorGraph:
    """Supervisor 不执行业务，只分类、委派并统一结果。"""

    def __init__(
        self,
        *,
        model: JSONGenerator,
        resume_agent: ResumeAgent,
        job_agent: JobAgent,
        interview_agent: InterviewAgent,
    ) -> None:
        self._model = model
        self._resume_agent = resume_agent
        self._job_agent = job_agent
        self._interview_agent = interview_agent
        builder = StateGraph(SupervisorState)
        builder.add_node("understand_intent", self._understand_intent)
        builder.add_node("supervisor", self._respond_directly)
        builder.add_node("resume_agent", self._delegate_resume)
        builder.add_node("job_agent", self._delegate_job)
        builder.add_node("interview_agent", self._delegate_interview)
        builder.add_node("combine_result", self._combine_result)
        builder.add_edge(START, "understand_intent")
        builder.add_conditional_edges(
            "understand_intent",
            self._route_agent,
            {
                "supervisor": "supervisor",
                "resume_agent": "resume_agent",
                "job_agent": "job_agent",
                "interview_agent": "interview_agent",
            },
        )
        builder.add_edge("supervisor", "combine_result")
        builder.add_edge("resume_agent", "combine_result")
        builder.add_edge("job_agent", "combine_result")
        builder.add_edge("interview_agent", "combine_result")
        builder.add_edge("combine_result", END)
        self._graph = builder.compile()

    async def run(self, state: SupervisorState) -> SupervisorState:
        """执行一次 Supervisor 调度。"""
        return await self._graph.ainvoke(state)

    async def _understand_intent(self, state: SupervisorState) -> dict[str, Any]:
        """先处理确定性上下文，再让模型判断其余自然语言意图。"""
        deterministic = self._infer_deterministic_route(state)
        if deterministic is not None:
            return deterministic
        route = await generate_structured_output(
            llm_client=self._model,
            system_prompt=build_supervisor_system_prompt(),
            user_prompt=build_supervisor_user_prompt(state["message"]),
            schema=SupervisorRoute,
            log_context="supervisor_route",
            validation_retries=1,
        )
        return {"route": route, "agent_trace": ["supervisor"]}

    @staticmethod
    def _infer_deterministic_route(state: SupervisorState) -> dict[str, Any] | None:
        """用可解释规则兜住 JD、面试回答和系统身份等高确定性意图。"""
        message = state["message"].strip()
        lowered = message.casefold()
        payload = dict(state["payload"])
        has_jd = isinstance(payload.get("jd_text"), str) and bool(payload["jd_text"].strip())
        if not has_jd and SupervisorGraph._looks_like_jd(message):
            payload["jd_text"] = message
            has_jd = True

        if payload.get("answer") and payload.get("interview_id"):
            route = SupervisorRoute(
                target_agent=AgentTarget.INTERVIEW,
                action=InterviewAgentAction.EVALUATE_ANSWER,
                reason="检测到当前面试问题的用户回答",
            )
        elif has_jd:
            if any(keyword in lowered for keyword in ("面试", "interview agent")):
                route = SupervisorRoute(
                    target_agent=AgentTarget.INTERVIEW,
                    action=InterviewAgentAction.CREATE_INTERVIEW_PLAN,
                    reason="用户提供了 JD，并希望进行岗位面试",
                )
            elif any(
                keyword in lowered
                for keyword in ("优化简历", "修改简历", "resume agent")
            ):
                route = SupervisorRoute(
                    target_agent=AgentTarget.RESUME,
                    action=ResumeAgentAction.OPTIMIZE_RESUME,
                    reason="用户提供了 JD，并希望针对岗位优化简历",
                )
            else:
                route = SupervisorRoute(
                    target_agent=AgentTarget.JOB,
                    action=JobSupervisorAction.ANALYZE_JOB,
                    reason="检测到完整 JD，默认进行岗位匹配分析",
                )
        elif lowered in {"你是谁", "你是什么", "你能做什么", "介绍一下你自己"}:
            route = SupervisorRoute(
                target_agent=AgentTarget.SUPERVISOR,
                action=SupervisorAction.RESPOND,
                reason="用户在询问 JobPilot 的身份或能力",
                reply=(
                    "我是 JobPilot AI 求职助手。我可以解析并保存 PDF 简历、构建候选人画像、"
                    "分析你粘贴的岗位 JD，并结合简历进行持续模拟面试。"
                ),
            )
        else:
            return None
        return {
            "route": route,
            "payload": payload,
            "agent_trace": ["supervisor"],
        }

    @staticmethod
    def _looks_like_jd(message: str) -> bool:
        """识别用户直接粘贴且未额外声明意图的岗位描述。"""
        if len(message) < 60:
            return False
        markers = (
            "岗位职责",
            "工作职责",
            "任职要求",
            "职位要求",
            "岗位要求",
            "工作内容",
            "技能要求",
            "职位描述",
        )
        signals = ("学历", "经验", "优先", "熟悉", "掌握", "负责")
        return any(marker in message for marker in markers) or sum(
            signal in message for signal in signals
        ) >= 3

    @staticmethod
    def _route_agent(state: SupervisorState) -> str:
        """根据经过 Schema 校验的 target_agent 选择领域 Agent。"""
        target = state["route"].target_agent.value
        return target if target == AgentTarget.SUPERVISOR.value else f"{target}_agent"

    @staticmethod
    def _respond_directly(state: SupervisorState) -> dict[str, Any]:
        """普通对话或上下文不足时直接答复，不触发任何业务 Tool。"""
        route = state["route"]
        return {
            "agent_result": {"result": {"message": route.reply}},
            "agent_trace": state["agent_trace"],
            "tool_trace": [],
        }

    async def _ensure_job_context(
        self,
        state: SupervisorState,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str], dict[str, Any] | None]:
        """附带新 JD 时先交给 Job Agent 完成解析、匹配和保存。"""
        if payload.get("job_id") is not None:
            prepared = dict(payload)
            prepared.pop("jd_text", None)
            return prepared, [], None
        jd_text = payload.get("jd_text")
        if not isinstance(jd_text, str) or not jd_text.strip():
            return payload, [], None
        try:
            result = await self._job_agent.analyze(
                JobAgentRequest(message="请分析这个岗位是否适合我。", jd_text=jd_text)
            )
        except AppException as exc:
            if exc.code == 40403:
                return payload, [], self._missing_context(
                    state,
                    "还没有候选人画像。请先点击附件按钮上传 PDF 简历，系统会自动生成画像。",
                    ["resume"],
                )
            raise
        prepared = {**payload, "job_id": result.job.id}
        prepared.pop("jd_text", None)
        return prepared, list(result.tool_trace), None

    async def _delegate_resume(self, state: SupervisorState) -> dict[str, Any]:
        """原样转交 payload，Supervisor 不重写参数。"""
        route = state["route"]
        payload = dict(state["payload"])
        preparation_trace: list[str] = []
        if route.action == ResumeAgentAction.OPTIMIZE_RESUME:
            payload, preparation_trace, missing = await self._ensure_job_context(
                state, payload
            )
            if missing is not None:
                return missing
            if payload.get("job_id") is None:
                return self._missing_context(
                    state,
                    "请粘贴目标岗位 JD，或在“上下文”中填写岗位 ID 后再优化简历。",
                    ["job_id", "jd_text"],
                )
        action = ResumeAgentAction(route.action)
        result = await self._resume_agent.execute(action=action, payload=payload)
        return {
            "agent_result": result.model_dump(mode="json"),
            "agent_trace": [*state["agent_trace"], "resume"],
            "tool_trace": [*preparation_trace, *result.tool_trace],
        }

    async def _delegate_job(self, state: SupervisorState) -> dict[str, Any]:
        """纯 JD 或岗位判断请求默认完成解析、规则匹配并保存结果。"""
        route = state["route"]
        if route.action != JobSupervisorAction.ANALYZE_JOB:
            raise ValueError("unsupported Job Agent action")
        raw_jd = state["payload"].get("jd_text")
        jd_text = raw_jd.strip() if isinstance(raw_jd, str) else ""
        if not jd_text:
            return self._missing_context(
                state,
                "请粘贴完整岗位 JD，我会自动解析并结合当前候选人画像计算匹配度。",
                ["jd_text"],
            )
        try:
            result = await self._job_agent.analyze(
                JobAgentRequest(message="请分析这个岗位是否适合我。", jd_text=jd_text)
            )
        except AppException as exc:
            if exc.code == 40403:
                return self._missing_context(
                    state,
                    "还没有候选人画像。请先点击附件按钮上传 PDF 简历，系统会自动生成画像。",
                    ["resume"],
                )
            raise
        return {
            "agent_result": {"result": result.model_dump(mode="json")},
            "agent_trace": [*state["agent_trace"], "job"],
            "tool_trace": list(result.tool_trace),
        }

    async def _delegate_interview(self, state: SupervisorState) -> dict[str, Any]:
        """将面试动作交给 Interview Agent。"""
        route = state["route"]
        payload = dict(state["payload"])
        preparation_trace: list[str] = []
        if route.action == InterviewAgentAction.CREATE_INTERVIEW_PLAN:
            payload, preparation_trace, missing = await self._ensure_job_context(
                state, payload
            )
            if missing is not None:
                return missing
            if payload.get("job_id") is None:
                return self._missing_context(
                    state,
                    "开始面试前，请粘贴目标岗位 JD，或在“上下文”中填写岗位 ID。",
                    ["job_id", "jd_text"],
                )
        elif route.action == InterviewAgentAction.EVALUATE_ANSWER:
            missing = [
                field
                for field in ("interview_id", "question_id", "answer")
                if not payload.get(field)
            ]
            if missing:
                return self._missing_context(
                    state,
                    "当前没有可回答的面试题，请先开始一场模拟面试。",
                    missing,
                )
        elif not payload.get("interview_id"):
            return self._missing_context(
                state,
                "请先开始一场模拟面试，再查看当前问题或累计薄弱点。",
                ["interview_id"],
            )
        result = await self._interview_agent.execute(
            action=InterviewAgentAction(route.action),
            payload=payload,
        )
        return {
            "agent_result": result.model_dump(mode="json"),
            "agent_trace": [*state["agent_trace"], "interview"],
            "tool_trace": [*preparation_trace, *result.tool_trace],
        }

    @staticmethod
    def _missing_context(
        state: SupervisorState,
        message: str,
        fields: list[str],
    ) -> dict[str, Any]:
        """把可恢复的参数缺失转换为引导信息，而不是 HTTP 422。"""
        return {
            "agent_result": {
                "result": {"message": message, "needs_input": fields}
            },
            "agent_trace": state["agent_trace"],
            "tool_trace": [],
        }

    @staticmethod
    def _combine_result(state: SupervisorState) -> dict[str, Any]:
        """组合统一响应，不重新解释或修改领域结果。"""
        route = state["route"]
        agent_result = state["agent_result"]
        response = SupervisorResponse(
            target_agent=route.target_agent,
            action=route.action,
            reason=route.reason,
            result=agent_result["result"],
            agent_trace=state["agent_trace"],
            tool_trace=state["tool_trace"],
        )
        return {"final_result": response.model_dump(mode="json")}
