"""Resume Agent 对外门面。"""

from typing import Any

from app.agents.resume_agent.graph import ResumeAgentGraph
from app.schemas.resume_agent import ResumeAgentAction, ResumeAgentResult
from app.services.profile_storage_service import ProfileStorageService
from app.services.resume_optimization_service import ResumeOptimizationService
from app.services.resume_rag_service import ResumeRagService
from app.services.resume_storage_service import ResumeStorageService
from app.tools.resume_agent_tools import (
    AnswerResumeTool,
    GetProfileTool,
    GetResumeTool,
    OptimizeResumeTool,
    UpdateProfileTool,
)


class ResumeAgent:
    """编排 Resume 领域 Tool，不承载数据库或 LLM 业务逻辑。"""

    def __init__(
        self,
        *,
        user_id: int,
        resume_service: ResumeStorageService,
        rag_service: ResumeRagService,
        profile_service: ProfileStorageService,
        optimization_service: ResumeOptimizationService,
        retrieval_limit: int,
    ) -> None:
        self._graph = ResumeAgentGraph(
            get_resume_tool=GetResumeTool(user_id=user_id, service=resume_service),
            answer_resume_tool=AnswerResumeTool(
                user_id=user_id,
                service=rag_service,
                retrieval_limit=retrieval_limit,
            ),
            get_profile_tool=GetProfileTool(user_id=user_id, service=profile_service),
            update_profile_tool=UpdateProfileTool(user_id=user_id, service=profile_service),
            optimize_resume_tool=OptimizeResumeTool(
                user_id=user_id,
                service=optimization_service,
            ),
        )

    async def execute(
        self,
        *,
        action: ResumeAgentAction,
        payload: dict[str, Any],
    ) -> ResumeAgentResult:
        """执行 Supervisor 委派的单一动作。"""
        state = await self._graph.run(
            {"action": action, "payload": payload, "tool_trace": []}
        )
        return ResumeAgentResult(
            action=action,
            result=state["result"],
            tool_trace=state["tool_trace"],
        )
