"""候选人 Profile Tool。"""

from collections.abc import Mapping
from typing import Any

from app.services.profile_storage_service import ProfileStorageService
from app.tools.base import AgentToolResult, BaseAgentTool


class GetCandidateProfileTool(BaseAgentTool):
    """将当前 Profile 查询 Service 包装为 Agent Tool。"""

    name = "get_candidate_profile"
    description = "查询当前用户已经保存的 Candidate Profile。"

    def __init__(self, *, user_id: int, service: ProfileStorageService) -> None:
        self._user_id = user_id
        self._service = service

    async def invoke(
        self,
        state: Mapping[str, Any],
        arguments: dict[str, Any],
    ) -> AgentToolResult:
        """查询当前 Profile，具体数据库读取由 Service/Repository 完成。"""
        del state
        self.ensure_no_arguments(arguments)
        profile = await self._service.get_current(self._user_id)
        data = profile.model_dump(mode="json")
        return AgentToolResult(content=data, state_updates={"profile": data})
