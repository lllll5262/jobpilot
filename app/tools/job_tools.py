"""JD 解析 Tool。"""

from collections.abc import Mapping
from typing import Any

from app.schemas.comparison import ComparisonJobSource
from app.schemas.persistence import ProfileRecord
from app.services.job_compare_service import JobCompareService
from app.services.job_storage_service import JobStorageService
from app.tools.base import AgentExecutionError, AgentToolResult, BaseAgentTool


class ParseJobDescriptionTool(BaseAgentTool):
    """将 JD 解析及保存 Service 包装为 Agent Tool。"""

    name = "parse_job_description"
    description = "解析用户提供的职位描述，并保存结构化岗位记录。"

    def __init__(self, *, user_id: int, service: JobStorageService) -> None:
        self._user_id = user_id
        self._service = service

    async def invoke(
        self,
        state: Mapping[str, Any],
        arguments: dict[str, Any],
    ) -> AgentToolResult:
        """从可信 Agent State 读取 JD，避免模型改写原始岗位内容。"""
        self.ensure_no_arguments(arguments)
        jd_text = state.get("jd_text")
        if not isinstance(jd_text, str) or not jd_text.strip():
            raise AgentExecutionError("Job description is missing from agent state")
        job = await self._service.parse_and_save(user_id=self._user_id, jd_text=jd_text)
        data = job.model_dump(mode="json")
        return AgentToolResult(content=data, state_updates={"job": data})


class CompareJobsTool(BaseAgentTool):
    """将多岗位对比 Service 包装为 Agent Tool。"""

    name = "compare_jobs"
    description = "读取历史或新粘贴 JD，分别匹配并生成技能差距、岗位排名和推荐理由。"

    def __init__(self, *, user_id: int, service: JobCompareService) -> None:
        self._user_id = user_id
        self._service = service

    async def invoke(
        self,
        state: Mapping[str, Any],
        arguments: dict[str, Any],
    ) -> AgentToolResult:
        """从可信 State 读取当前 Profile 和待比较岗位。"""
        self.ensure_no_arguments(arguments)
        raw_profile = state.get("profile")
        raw_sources = state.get("comparison_sources")
        if not isinstance(raw_profile, dict):
            raise AgentExecutionError("Candidate profile is missing from agent state")
        if not isinstance(raw_sources, list):
            raise AgentExecutionError("Comparison jobs are missing from agent state")
        profile = ProfileRecord.model_validate(raw_profile)
        sources = [ComparisonJobSource.model_validate(source) for source in raw_sources]
        result = await self._service.compare(
            user_id=self._user_id,
            sources=sources,
            profile=profile.profile,
        )
        data = result.model_dump(mode="json")
        return AgentToolResult(content=data, state_updates={"comparison": data})
