"""Supervisor Agent 对外门面。"""

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
    ) -> None:
        self._graph = SupervisorGraph(
            model=model,
            resume_agent=resume_agent,
            job_agent=job_agent,
            interview_agent=interview_agent,
        )

    async def handle(self, request: SupervisorRequest) -> SupervisorResponse:
        """处理统一入口请求。"""
        state = await self._graph.run(
            {
                "message": request.message,
                "payload": request.payload,
                "agent_trace": [],
                "tool_trace": [],
            }
        )
        return SupervisorResponse.model_validate(state["final_result"])
