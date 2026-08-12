"""Job Agent 对外门面。"""

from app.agents.job_agent.graph import JobAgentGraph
from app.agents.job_agent.state import JobAgentState
from app.llm.client import ToolCallingModel
from app.schemas.agent import JobAgentRequest, JobAgentResponse
from app.schemas.persistence import AnalysisRecord
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
    ) -> None:
        self._graph = JobAgentGraph(
            model,
            [
                GetCandidateProfileTool(user_id=user_id, service=profile_service),
                ParseJobDescriptionTool(user_id=user_id, service=job_service),
                CalculateJobMatchTool(user_id=user_id, service=analysis_service),
                SaveAnalysisTool(user_id=user_id, service=analysis_service),
            ],
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
        }
        result = await self._graph.run(initial_state)
        analysis = AnalysisRecord.model_validate(result["analysis"])
        return JobAgentResponse(
            final_answer=result["final_answer"],
            analysis=analysis,
            tool_trace=result["tool_trace"],
        )
