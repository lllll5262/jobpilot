"""Resume Agent 请求、优化建议和统一执行结果。"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.persistence import ProfileRecord, ResumeRecord


class ResumeAgentAction(StrEnum):
    """Resume Agent 当前支持的动作。"""

    GET_RESUME = "get_resume"
    ANSWER_RESUME = "answer_resume"
    GET_PROFILE = "get_profile"
    UPDATE_PROFILE = "update_profile"
    OPTIMIZE_RESUME = "optimize_resume"


class ResumeAgentPayload(BaseModel):
    """Supervisor 原样转交给 Resume Agent 的可信参数。"""

    model_config = ConfigDict(extra="forbid")

    resume_id: int | None = Field(default=None, gt=0)
    job_id: int | None = Field(default=None, gt=0)
    query: str | None = Field(default=None, min_length=1, max_length=2_000)


class ResumeOptimizationSuggestion(BaseModel):
    """针对结构化简历中一处已有文本的修改建议。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    section: str = Field(min_length=1)
    location: str = Field(min_length=1)
    original_text: str = Field(min_length=1)
    suggested_text: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    jd_keywords: list[str] = Field(default_factory=list)


class ResumeOptimizationDraft(BaseModel):
    """LLM 生成的项目分析和建议，不直接修改数据库简历。"""

    model_config = ConfigDict(extra="forbid")

    project_analysis: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    suggestions: list[ResumeOptimizationSuggestion] = Field(default_factory=list)


class ResumeOptimizationResult(ResumeOptimizationDraft):
    """带 Resume、Profile 和 Job 标识的优化结果。"""

    resume_id: int
    profile_id: int
    job_id: int
    limitation: str


class ResumeAgentResult(BaseModel):
    """Resume Agent 对 Supervisor 返回的统一结果。"""

    action: ResumeAgentAction
    result: dict[str, Any]
    tool_trace: list[str]


class ResumeContextResult(BaseModel):
    """读取动作返回的领域对象联合类型。"""

    resume: ResumeRecord | None = None
    profile: ProfileRecord | None = None

    @model_validator(mode="after")
    def require_one_context(self) -> "ResumeContextResult":
        """一次读取 Tool 只返回一种上下文。"""
        if (self.resume is None) == (self.profile is None):
            raise ValueError("exactly one resume context is required")
        return self
