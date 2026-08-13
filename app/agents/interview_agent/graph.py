"""自适应面试 LangGraph 编排。"""

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.interview_agent.state import InterviewAgentState
from app.tools.interview_tools import AnswerInterviewTool, StartInterviewTool


class InterviewAgentGraph:
    """根据明确 action 执行一个业务 Tool，LLM 不能修改用户和会话 ID。"""

    def __init__(
        self,
        *,
        start_tool: StartInterviewTool,
        answer_tool: AnswerInterviewTool,
    ) -> None:
        self._start_tool = start_tool
        self._answer_tool = answer_tool
        builder = StateGraph(InterviewAgentState)
        builder.add_node("start_interview", self._start_interview)
        builder.add_node("answer_interview", self._answer_interview)
        builder.add_conditional_edges(
            START,
            self._route_action,
            {
                "start_interview": "start_interview",
                "answer_interview": "answer_interview",
            },
        )
        builder.add_edge("start_interview", END)
        builder.add_edge("answer_interview", END)
        self._graph = builder.compile()

    async def run(self, state: InterviewAgentState) -> InterviewAgentState:
        """执行一轮面试状态转换。"""
        return await self._graph.ainvoke(state)

    @staticmethod
    def _route_action(state: InterviewAgentState) -> str:
        """由可信 action 决定启动或继续面试分支。"""
        return "start_interview" if state["action"] == "start" else "answer_interview"

    async def _start_interview(self, state: InterviewAgentState) -> dict[str, Any]:
        """执行简历首问 Tool。"""
        result = await self._start_tool.invoke(state["payload"])
        return {"result": result, "tool_trace": [self._start_tool.name]}

    async def _answer_interview(self, state: InterviewAgentState) -> dict[str, Any]:
        """执行答案评价及下一题选择 Tool。"""
        result = await self._answer_tool.invoke(state["payload"])
        return {"result": result, "tool_trace": [self._answer_tool.name]}
