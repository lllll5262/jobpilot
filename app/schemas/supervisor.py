"""Supervisor Agent 路由协议。"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.interview import InterviewAgentAction
from app.schemas.resume_agent import ResumeAgentAction


class AgentTarget(StrEnum):
    """Supervisor 可以委派的业务 Agent。"""

    SUPERVISOR = "supervisor"
    RESUME = "resume"
    JOB = "job"
    INTERVIEW = "interview"


class SupervisorAction(StrEnum):
    """不需要业务 Tool 时，由 Supervisor 直接完成的动作。"""

    RESPOND = "respond"
    REQUEST_CONTEXT = "request_context"


class JobSupervisorAction(StrEnum):
    """Supervisor 当前允许交给 Job Agent 的动作。"""

    ANALYZE_JOB = "analyze_job"


class SupervisorRequest(BaseModel):
    """统一多 Agent 入口请求。"""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=20_000)
    payload: dict[str, Any] = Field(default_factory=dict)


class SupervisorRoute(BaseModel):
    """Supervisor LLM 只允许选择目标和动作，不生成业务参数。"""

    model_config = ConfigDict(extra="forbid")

    target_agent: AgentTarget
    action: SupervisorAction | ResumeAgentAction | JobSupervisorAction | InterviewAgentAction
    reason: str = Field(min_length=1)
    reply: str | None = Field(
        default=None,
        description="仅 Supervisor 直接响应时填写的简短中文答复",
    )

    @model_validator(mode="after")
    def action_must_belong_to_target(self) -> "SupervisorRoute":
        """禁止把一个领域动作派发给另一个 Agent。"""
        if self.target_agent == AgentTarget.SUPERVISOR and not isinstance(
            self.action, SupervisorAction
        ):
            raise ValueError("supervisor target requires a supervisor action")
        if self.target_agent == AgentTarget.RESUME and not isinstance(
            self.action, ResumeAgentAction
        ):
            raise ValueError("resume target requires a resume action")
        if self.target_agent == AgentTarget.JOB and not isinstance(
            self.action, JobSupervisorAction
        ):
            raise ValueError("job target requires a job action")
        if self.target_agent == AgentTarget.INTERVIEW and not isinstance(
            self.action, InterviewAgentAction
        ):
            raise ValueError("interview target requires an interview action")
        if self.target_agent == AgentTarget.SUPERVISOR and not self.reply:
            raise ValueError("supervisor response requires reply")
        return self


class SupervisorResponse(BaseModel):
    """Supervisor 汇总领域结果后的统一响应。"""

    target_agent: AgentTarget
    action: SupervisorAction | ResumeAgentAction | JobSupervisorAction | InterviewAgentAction
    reason: str
    result: dict[str, Any]
    agent_trace: list[str]
    tool_trace: list[str]
