"""Resume Agent LangGraph 状态。"""

from typing import Any, NotRequired, TypedDict

from app.schemas.resume_agent import ResumeAgentAction


class ResumeAgentState(TypedDict):
    """一次 Resume 领域动作的可信状态。"""

    action: ResumeAgentAction
    payload: dict[str, Any]
    tool_trace: list[str]
    result: NotRequired[dict[str, Any]]
