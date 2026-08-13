"""自适应面试 LangGraph 状态。"""

from typing import Any, Literal, NotRequired, TypedDict


class InterviewAgentState(TypedDict):
    """API 与面试 Tool 之间传递的可信状态。"""

    action: Literal["start", "answer"]
    payload: dict[str, Any]
    result: NotRequired[dict[str, Any]]
    tool_trace: list[str]
