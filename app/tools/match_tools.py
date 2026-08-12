"""岗位匹配计算与保存 Tool。"""

from collections.abc import Mapping
from typing import Any

from app.schemas.persistence import AnalysisDraft, JobRecord
from app.services.analysis_storage_service import AnalysisStorageService
from app.tools.base import AgentExecutionError, AgentToolResult, BaseAgentTool


class CalculateJobMatchTool(BaseAgentTool):
    """调用 MatchService 及规则引擎计算结果，不执行保存。"""

    name = "calculate_job_match"
    description = "结合当前 Profile、Resume 和已解析 JD 计算岗位匹配结果。"

    def __init__(self, *, user_id: int, service: AnalysisStorageService) -> None:
        self._user_id = user_id
        self._service = service

    async def invoke(
        self,
        state: Mapping[str, Any],
        arguments: dict[str, Any],
    ) -> AgentToolResult:
        """只做状态适配，实际语义判断和规则算分仍由 Service 完成。"""
        self.ensure_no_arguments(arguments)
        raw_job = state.get("job")
        if not isinstance(raw_job, dict):
            raise AgentExecutionError("Parsed job is missing from agent state")
        job = JobRecord.model_validate(raw_job)
        draft = await self._service.calculate(user_id=self._user_id, job_id=job.id)
        data = draft.model_dump(mode="json")
        return AgentToolResult(content=data, state_updates={"match_draft": data})


class SaveAnalysisTool(BaseAgentTool):
    """保存已经计算完成的匹配草稿。"""

    name = "save_analysis"
    description = "将已经计算完成的岗位匹配结果保存到历史分析。"

    def __init__(self, *, user_id: int, service: AnalysisStorageService) -> None:
        self._user_id = user_id
        self._service = service

    async def invoke(
        self,
        state: Mapping[str, Any],
        arguments: dict[str, Any],
    ) -> AgentToolResult:
        """校验 Graph 中的分析草稿，再交给 Service 持久化。"""
        self.ensure_no_arguments(arguments)
        raw_draft = state.get("match_draft")
        if not isinstance(raw_draft, dict):
            raise AgentExecutionError("Match draft is missing from agent state")
        draft = AnalysisDraft.model_validate(raw_draft)
        if draft.user_id != self._user_id:
            raise AgentExecutionError("Match draft does not belong to current user")
        analysis = await self._service.save(draft)
        data = analysis.model_dump(mode="json")
        return AgentToolResult(content=data, state_updates={"analysis": data})
