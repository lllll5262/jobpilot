"""Job Agent 在一次 LangGraph 运行中的显式状态。"""

import operator
from typing import Annotated, Any, NotRequired, TypedDict

from app.schemas.agent import JobAgentToolName


class JobAgentState(TypedDict):
    """节点间共享的状态；列表字段通过 reducer 追加而非覆盖。"""

    messages: Annotated[list[dict[str, Any]], operator.add]
    tool_trace: Annotated[list[JobAgentToolName], operator.add]
    user_id: int
    jd_text: str | None
    requires_analysis: bool
    analysis_context: list[dict[str, Any]]
    session_id: NotRequired[str]
    turn: NotRequired[int]
    profile: NotRequired[dict[str, Any]]
    job: NotRequired[dict[str, Any]]
    match_draft: NotRequired[dict[str, Any]]
    analysis: NotRequired[dict[str, Any]]
    final_answer: NotRequired[str]
