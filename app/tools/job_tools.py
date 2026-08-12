"""JD 解析 Tool。"""

from collections.abc import Mapping
from typing import Any

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
