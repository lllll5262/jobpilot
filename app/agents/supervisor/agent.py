"""Supervisor Agent 对外门面。"""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agents.interview_agent import InterviewAgent
from app.agents.job_agent import JobAgent
from app.agents.resume_agent import ResumeAgent
from app.agents.supervisor.graph import SupervisorGraph
from app.llm.client import JSONGenerator
from app.schemas.supervisor import SupervisorRequest, SupervisorResponse


class SupervisorAgent:
    """只负责意图理解、领域委派、状态管理和结果组合。"""

    def __init__(
        self,
        *,
        model: JSONGenerator,
        resume_agent: ResumeAgent,
        job_agent: JobAgent,
        interview_agent: InterviewAgent,
        user_id: int,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
    ) -> None:
        self._user_id = user_id
        self._graph = SupervisorGraph(
            model=model,
            resume_agent=resume_agent,
            job_agent=job_agent,
            interview_agent=interview_agent,
            checkpointer=checkpointer,
        )

    async def handle(self, request: SupervisorRequest) -> SupervisorResponse:
        """处理统一入口请求。"""
        state = await self._graph.run(
            {
                "user_id": self._user_id,
                "session_id": request.session_id,
                "message": request.message,
                "payload": request.payload,
                "agent_trace": [],
                "tool_trace": [],
            },
            # 同一用户的同一前端对话始终使用同一个线程，避免跨用户串状态。
            thread_id=f"supervisor:user:{self._user_id}:session:{request.session_id}",
        )
        return SupervisorResponse.model_validate(state["final_result"])
