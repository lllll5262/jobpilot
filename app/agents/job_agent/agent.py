"""Job Agent 对外门面。"""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agents.job_agent.graph import JobAgentGraph
from app.agents.job_agent.state import JobAgentState
from app.llm.client import ToolCallingModel
from app.schemas.agent import (
    ConversationMessage,
    JobAgentRequest,
    JobAgentResponse,
    JobAgentSessionRequest,
    JobAgentSessionResponse,
)
from app.schemas.persistence import AnalysisRecord, JobRecord
from app.services.analysis_storage_service import AnalysisStorageService
from app.services.job_storage_service import JobStorageService
from app.services.profile_storage_service import ProfileStorageService
from app.tools.job_tools import ParseJobDescriptionTool
from app.tools.match_tools import CalculateJobMatchTool, SaveAnalysisTool
from app.tools.profile_tools import GetCandidateProfileTool


class JobAgent:
    """组装模型、Graph 与业务 Tool，执行完整岗位分析。"""

    def __init__(
        self,
        *,
        model: ToolCallingModel,
        user_id: int,
        profile_service: ProfileStorageService,
        job_service: JobStorageService,
        analysis_service: AnalysisStorageService,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
    ) -> None:
        self._graph = JobAgentGraph(
            model,
            [
                GetCandidateProfileTool(user_id=user_id, service=profile_service),
                ParseJobDescriptionTool(user_id=user_id, service=job_service),
                CalculateJobMatchTool(user_id=user_id, service=analysis_service),
                SaveAnalysisTool(user_id=user_id, service=analysis_service),
            ],
            checkpointer=checkpointer,
        )
        self._user_id = user_id

    async def analyze(self, request: JobAgentRequest) -> JobAgentResponse:
        """运行单 Agent，并返回自然语言结论和已保存的结构化结果。"""
        initial_state: JobAgentState = {
            "messages": [
                {
                    "role": "user",
                    "content": f"{request.message}\n\n岗位描述：\n{request.jd_text}",
                }
            ],
            "tool_trace": [],
            "user_id": self._user_id,
            "jd_text": request.jd_text,
            "requires_analysis": True,
            "analysis_context": [],
        }
        result = await self._graph.run(initial_state)
        analysis = AnalysisRecord.model_validate(result["analysis"])
        job = JobRecord.model_validate(result["job"])
        return JobAgentResponse(
            final_answer=result["final_answer"],
            analysis=analysis,
            job=job,
            tool_trace=result["tool_trace"],
        )

    async def chat(
        self,
        request: JobAgentSessionRequest,
        *,
        turn: int,
        history: list[ConversationMessage],
        analysis_context: list[dict[str, Any]],
    ) -> JobAgentSessionResponse:
        """携带最近对话与岗位摘要执行一轮可恢复的 Agent 会话。"""
        messages = [{"role": message.role, "content": message.content} for message in history]
        current_content = request.message
        if request.jd_text is not None:
            current_content = f"{current_content}\n\n岗位描述：\n{request.jd_text}"
        messages.append({"role": "user", "content": current_content})
        initial_state: JobAgentState = {
            "messages": messages,
            "tool_trace": [],
            "user_id": self._user_id,
            "jd_text": request.jd_text,
            "requires_analysis": request.jd_text is not None,
            "analysis_context": analysis_context,
            "session_id": request.session_id,
            "turn": turn,
        }
        result = await self._graph.run(
            initial_state,
            # checkpoint_ns 由 LangGraph 内部管理；每轮使用独立 thread_id 隔离状态。
            thread_id=f"{request.session_id}:turn:{turn}",
        )
        raw_analysis = result.get("analysis")
        raw_job = result.get("job")
        return JobAgentSessionResponse(
            session_id=request.session_id,
            turn=turn,
            final_answer=result["final_answer"],
            analysis=AnalysisRecord.model_validate(raw_analysis) if raw_analysis else None,
            job=JobRecord.model_validate(raw_job) if raw_job else None,
            tool_trace=result["tool_trace"],
            history_turns=len(history) // 2,
        )
