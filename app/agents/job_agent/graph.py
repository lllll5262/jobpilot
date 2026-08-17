"""Job Agent 的 LangGraph 状态图。"""

import json
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from app.agents.job_agent.prompt import build_job_agent_system_prompt
from app.agents.job_agent.state import JobAgentState
from app.llm.client import ToolCallingModel
from app.schemas.agent import JobAgentToolName
from app.tools.base import AgentExecutionError, BaseAgentTool

ANALYSIS_TOOL_ORDER: tuple[JobAgentToolName, ...] = (
    "get_candidate_profile",
    "parse_job_description",
    "calculate_job_match",
    "save_analysis",
)


class JobAgentGraph:
    """让模型发起 Tool Calling，并由 LangGraph 驱动状态循环。"""

    def __init__(
        self,
        model: ToolCallingModel,
        tools: list[BaseAgentTool],
    ) -> None:
        self._model = model
        self._tools = {tool.name: tool for tool in tools}
        analysis_tools = set(ANALYSIS_TOOL_ORDER)
        optional_tools = {"compare_jobs"}
        unexpected_tools = set(self._tools) - analysis_tools - optional_tools
        if not analysis_tools.issubset(self._tools) or unexpected_tools:
            raise ValueError("Job Agent tools are incomplete")

        builder = StateGraph(JobAgentState)
        builder.add_node("agent", self._call_model)
        builder.add_node("tools", self._execute_tool)
        builder.add_edge(START, "agent")
        builder.add_conditional_edges(
            "agent",
            self._route_after_agent,
            {"tools": "tools", "end": END},
        )
        builder.add_edge("tools", "agent")
        # 子 Agent 不单独保存 Checkpoint，避免与 Supervisor 的会话快照重复。
        self._graph = builder.compile()

    async def run(
        self,
        state: JobAgentState,
    ) -> JobAgentState:
        """执行一次有界 Agent 循环，防止模型异常导致无限调用。"""
        return await self._graph.ainvoke(state, config={"recursion_limit": 12})

    async def _call_model(self, state: JobAgentState) -> dict[str, Any]:
        """只暴露当前状态所允许的下一步 Tool。"""
        next_tool = self._next_required_tool(state)
        definitions = [self._tools[next_tool].definition] if next_tool else []
        messages = [
            {
                "role": "system",
                "content": build_job_agent_system_prompt(
                    next_tool,
                    state["analysis_context"],
                ),
            },
            *state["messages"],
        ]
        response = await self._model.generate_with_tools(
            messages=messages,
            tools=definitions,
            require_tool=next_tool is not None,
        )

        if next_tool is not None:
            if len(response.tool_calls) != 1:
                raise AgentExecutionError("Agent must call exactly one required tool")
            if response.tool_calls[0].function.name != next_tool:
                raise AgentExecutionError(
                    "Agent called a tool that is not allowed in current state"
                )
            # Tool Calling 历史需要保留 content=null，兼容要求该字段存在的供应商。
            return {"messages": [response.model_dump(mode="json")]}

        if response.tool_calls:
            raise AgentExecutionError("Agent called a tool after workflow completion")
        final_answer = (response.content or "").strip()
        if not final_answer:
            raise AgentExecutionError("Agent returned an empty final answer")
        return {
            "messages": [response.model_dump(mode="json")],
            "final_answer": final_answer,
        }

    async def _execute_tool(self, state: JobAgentState) -> dict[str, Any]:
        """执行模型指定的工具，并将结果同时写入消息历史和领域状态。"""
        message = state["messages"][-1]
        raw_calls = message.get("tool_calls")
        if not isinstance(raw_calls, list) or len(raw_calls) != 1:
            raise AgentExecutionError("Agent tool call is missing")

        raw_call = raw_calls[0]
        try:
            call_id = raw_call["id"]
            function = raw_call["function"]
            tool_name = function["name"]
            arguments = json.loads(function.get("arguments") or "{}")
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise AgentExecutionError("Agent returned invalid tool call arguments") from exc
        if tool_name not in self._tools or not isinstance(arguments, dict):
            raise AgentExecutionError("Agent requested an unknown or invalid tool")

        tool = self._tools[tool_name]
        result = await tool.invoke(state, arguments)
        tool_message = {
            "role": "tool",
            "tool_call_id": call_id,
            "name": tool_name,
            "content": json.dumps(result.content, ensure_ascii=False),
        }
        return {
            "messages": [tool_message],
            "tool_trace": [tool.name],
            **result.state_updates,
        }

    @staticmethod
    def _route_after_agent(state: JobAgentState) -> Literal["tools", "end"]:
        """assistant 含工具调用时进入工具节点，否则结束。"""
        return "tools" if state["messages"][-1].get("tool_calls") else "end"

    @staticmethod
    def _next_required_tool(state: JobAgentState) -> JobAgentToolName | None:
        """依据领域状态确定唯一合法的下一步工具。"""
        if state["requires_comparison"]:
            if not state.get("profile"):
                return "get_candidate_profile"
            return None if state.get("comparison") else "compare_jobs"
        if not state["requires_analysis"]:
            return None
        if not state.get("profile"):
            return "get_candidate_profile"
        if not state.get("job"):
            return "parse_job_description"
        if not state.get("match_draft"):
            return "calculate_job_match"
        if not state.get("analysis"):
            return "save_analysis"
        return None
