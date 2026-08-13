"""Supervisor Agent LangGraph 状态。"""

from typing import Any, NotRequired, TypedDict

from app.schemas.supervisor import SupervisorRoute


class SupervisorState(TypedDict):
    """Supervisor 只管理路由、原始状态和组合结果。"""

    message: str
    payload: dict[str, Any]
    route: NotRequired[SupervisorRoute]
    agent_result: NotRequired[dict[str, Any]]
    final_result: NotRequired[dict[str, Any]]
    agent_trace: list[str]
    tool_trace: list[str]
