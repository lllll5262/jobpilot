"""Job Agent 的接口请求与响应模型。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.comparison import JobComparisonResult
from app.schemas.persistence import AnalysisRecord, JobRecord

JobAgentToolName = Literal[
    "get_candidate_profile",
    "parse_job_description",
    "calculate_job_match",
    "save_analysis",
    "compare_jobs",
]


class ConversationMessage(BaseModel):
    """最近 N 轮 Memory 中对外可见的用户或助手消息。"""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class JobAgentRequest(BaseModel):
    """请求单 Agent 完成一次岗位分析闭环。"""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(
        default="帮我分析一下这个岗位适不适合我。",
        min_length=1,
        max_length=2_000,
    )
    jd_text: str = Field(min_length=1, max_length=20_000)

    @field_validator("message", "jd_text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """去除首尾空白，并拒绝空内容。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("text must not be blank")
        return normalized


class JobAgentResponse(BaseModel):
    """Agent 最终回答以及本次落库的结构化分析。"""

    final_answer: str
    analysis: AnalysisRecord
    job: JobRecord
    tool_trace: list[JobAgentToolName]


class JobAgentComparisonResponse(BaseModel):
    """Agent 最终回答以及确定性的结构化岗位排名。"""

    final_answer: str
    comparison: JobComparisonResult
    tool_trace: list[JobAgentToolName]


class JobAgentSessionRequest(BaseModel):
    """多轮 Job Agent 请求；只有分析新岗位时才需要 jd_text。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    message: str = Field(min_length=1, max_length=2_000)
    jd_text: str | None = Field(default=None, min_length=1, max_length=20_000)

    @field_validator("session_id", "message", "jd_text")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """清理文本，并拒绝纯空白值。"""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("text must not be blank")
        return normalized


class JobAgentSessionResponse(BaseModel):
    """带 Session 信息的 Agent 单轮响应。"""

    session_id: str
    turn: int
    final_answer: str
    analysis: AnalysisRecord | None
    job: JobRecord | None
    tool_trace: list[JobAgentToolName]
    history_turns: int


class JobAgentSessionState(BaseModel):
    """当前 Session 的短期对话和岗位分析缓存。"""

    session_id: str
    messages: list[ConversationMessage]
    recent_analyses: list[dict[str, Any]]
