"""Resume Agent 动作路由 Graph。"""

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.resume_agent.state import ResumeAgentState
from app.schemas.resume_agent import ResumeAgentAction, ResumeAgentPayload
from app.tools.resume_agent_tools import (
    GetProfileTool,
    GetResumeTool,
    OptimizeResumeTool,
    UpdateProfileTool,
)


class ResumeAgentGraph:
    """将显式 Resume 动作路由到唯一 Tool。"""

    def __init__(
        self,
        *,
        get_resume_tool: GetResumeTool,
        get_profile_tool: GetProfileTool,
        update_profile_tool: UpdateProfileTool,
        optimize_resume_tool: OptimizeResumeTool,
    ) -> None:
        self._tools = {
            ResumeAgentAction.GET_RESUME: get_resume_tool,
            ResumeAgentAction.GET_PROFILE: get_profile_tool,
            ResumeAgentAction.UPDATE_PROFILE: update_profile_tool,
            ResumeAgentAction.OPTIMIZE_RESUME: optimize_resume_tool,
        }
        builder = StateGraph(ResumeAgentState)
        for action in ResumeAgentAction:
            builder.add_node(action.value, self._build_tool_node(action))
            builder.add_edge(action.value, END)
        builder.add_conditional_edges(
            START,
            self._route_action,
            {action.value: action.value for action in ResumeAgentAction},
        )
        self._graph = builder.compile()

    async def run(self, state: ResumeAgentState) -> ResumeAgentState:
        """执行一个 Resume Tool。"""
        return await self._graph.ainvoke(state)

    @staticmethod
    def _route_action(state: ResumeAgentState) -> str:
        """动作由 Supervisor 选择，但业务参数不由 Supervisor 改写。"""
        return state["action"].value

    def _build_tool_node(self, action: ResumeAgentAction):
        """为每个动作创建独立节点，便于测试和追踪。"""
        async def call_tool(state: ResumeAgentState) -> dict[str, Any]:
            payload = ResumeAgentPayload.model_validate(state["payload"])
            tool = self._tools[action]
            result = await tool.invoke(payload)
            return {"result": result, "tool_trace": [tool.name]}

        return call_tool
