"""Job Agent 的接口请求与响应模型。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.persistence import AnalysisRecord

JobAgentToolName = Literal[
    "get_candidate_profile",
    "parse_job_description",
    "calculate_job_match",
    "save_analysis",
]


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
    tool_trace: list[JobAgentToolName]
