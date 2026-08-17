"""阶段 10 自适应面试的数据模型。"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InterviewModel(BaseModel):
    """面试模块的严格 Schema 基类。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class QuestionSource(StrEnum):
    """当前问题的生成依据。"""

    RESUME = "resume"
    FOLLOW_UP = "follow_up"
    JD = "jd"
    REQUESTED = "requested"


class InterviewAgentAction(StrEnum):
    """Interview Agent 对外公开的动作协议。"""

    CREATE_INTERVIEW_PLAN = "create_interview_plan"
    GENERATE_QUESTIONS = "generate_questions"
    REQUEST_TOPIC = "request_topic"
    EVALUATE_ANSWER = "evaluate_answer"
    GET_WEAK_POINTS = "get_weak_points"


class AnswerQuality(StrEnum):
    """决定下一题方向的答案掌握程度。"""

    INCORRECT = "incorrect"
    PARTIAL = "partial"
    MASTERED = "mastered"


class InterviewStartRequest(InterviewModel):
    """使用历史岗位启动一场自适应面试。"""

    job_id: int = Field(gt=0)


class InterviewAnswerRequest(InterviewModel):
    """回答当前尚未作答的问题。"""

    question_id: str = Field(min_length=2, max_length=32)
    answer: str = Field(min_length=1, max_length=10_000)

    @field_validator("answer")
    @classmethod
    def reject_blank_answer(cls, answer: str) -> str:
        """拒绝空白回答。"""
        if not answer.strip():
            raise ValueError("answer must not be blank")
        return answer


class InterviewQuestionDraft(InterviewModel):
    """由 LLM 生成、尚未分配稳定 ID 的问题。"""

    topic: str = Field(min_length=1)
    question: str = Field(min_length=1)
    focus_points: list[str] = Field(min_length=1)
    source_basis: str = Field(min_length=1)


class InterviewQuestion(InterviewQuestionDraft):
    """实际向用户提出的问题。"""

    question_id: str = Field(min_length=2, max_length=32)
    source: QuestionSource


class InterviewEvaluationDraft(InterviewModel):
    """LLM 对一次回答的结构化评价。"""

    score: int = Field(ge=0, le=100)
    quality: AnswerQuality
    errors: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    weak_points: list[str] = Field(default_factory=list)
    correct_answer: str = Field(min_length=1)


class InterviewEvaluation(InterviewEvaluationDraft):
    """包含用户原回答的持久化评价。"""

    user_answer: str = Field(min_length=1)


class InterviewRound(InterviewModel):
    """数据库中保存的一轮真实问答。"""

    sequence: int = Field(ge=1)
    question: InterviewQuestion
    evaluation: InterviewEvaluation | None = None


class InterviewSessionRecord(InterviewModel):
    """一场面试及其完整问答汇总。"""

    id: int
    user_id: int
    resume_id: int
    profile_id: int
    job_id: int
    job_title: str
    rounds: list[InterviewRound]
    weak_points: list[str]
    average_score: int | None
    current_question: InterviewQuestion | None
    created_at: datetime
    updated_at: datetime


class InterviewAnswerResponse(InterviewModel):
    """回答后的错误说明、正确答案和下一题。"""

    evaluation: InterviewEvaluation
    next_question: InterviewQuestion | None
    session: InterviewSessionRecord


class InterviewAgentPayload(InterviewModel):
    """Supervisor 转交给 Interview Agent 的可信参数。"""

    job_id: int | None = Field(default=None, gt=0)
    interview_id: int | None = Field(default=None, gt=0)
    question_id: str | None = Field(default=None, min_length=2, max_length=32)
    answer: str | None = Field(default=None, min_length=1, max_length=10_000)
    topic: str | None = Field(default=None, min_length=1, max_length=100)


class InterviewWeakPointSummary(InterviewModel):
    """从已保存评价确定性聚合出的薄弱点。"""

    topic: str
    occurrences: int = Field(ge=1)
    latest_score: int = Field(ge=0, le=100)


class InterviewAgentResult(InterviewModel):
    """Interview Agent 对 Supervisor 返回的统一结果。"""

    action: str
    result: dict[str, Any]
    tool_trace: list[str]
