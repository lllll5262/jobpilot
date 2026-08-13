"""多岗位对比与技能差距分析数据模型。"""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.match import Recommendation


class ComparisonJobSource(BaseModel):
    """一个待比较岗位，可引用历史 JD 或提交新的 JD 文本。"""

    model_config = ConfigDict(extra="forbid")

    job_id: int | None = Field(default=None, gt=0)
    jd_text: str | None = Field(default=None, min_length=1, max_length=20_000)
    label: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("jd_text", "label")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """清理可选文本，并拒绝纯空白内容。"""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("text must not be blank")
        return normalized

    @model_validator(mode="after")
    def require_exactly_one_source(self) -> "ComparisonJobSource":
        """历史 ID 与新 JD 必须二选一，避免来源含义不明确。"""
        if (self.job_id is None) == (self.jd_text is None):
            raise ValueError("exactly one of job_id and jd_text is required")
        return self


class JobComparisonRequest(BaseModel):
    """Job Agent 多岗位对比请求。"""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(
        default="请比较这些岗位，告诉我哪个更适合。",
        min_length=1,
        max_length=2_000,
    )
    jobs: list[ComparisonJobSource] = Field(min_length=2, max_length=5)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        """清理用户问题。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized

    @field_validator("jobs")
    @classmethod
    def reject_duplicate_sources(
        cls,
        jobs: list[ComparisonJobSource],
    ) -> list[ComparisonJobSource]:
        """同一个历史岗位或相同 JD 文本不能重复参与比较。"""
        keys: set[tuple[str, int | str]] = set()
        for job in jobs:
            key: tuple[str, int | str]
            if job.job_id is not None:
                key = ("id", job.job_id)
            else:
                key = ("text", (job.jd_text or "").casefold())
            if key in keys:
                raise ValueError("comparison jobs must be unique")
            keys.add(key)
        return jobs


class JobGapInsight(BaseModel):
    """LLM 针对单个岗位给出的非数值语义分析。"""

    model_config = ConfigDict(extra="forbid")

    job_id: int = Field(gt=0)
    advantages: list[str]
    disadvantages: list[str]
    skill_gap_actions: list[str]


class ComparisonSemanticAssessment(BaseModel):
    """LLM 输出的差距说明，不允许包含或修改岗位分数。"""

    model_config = ConfigDict(extra="forbid")

    job_insights: list[JobGapInsight]
    recommendation_reason: str = Field(min_length=1)


class JobComparisonItem(BaseModel):
    """规则分数和语义差距合并后的单岗位结果。"""

    rank: int = Field(ge=1)
    job_id: int = Field(gt=0)
    job: str
    score: int = Field(ge=0, le=100)
    recommendation: Recommendation
    matched_skills: list[str]
    missing_skills: list[str]
    strong_points: list[str]
    weak_points: list[str]
    advantages: list[str]
    disadvantages: list[str]
    skill_gap_actions: list[str]


class JobComparisonResult(BaseModel):
    """按规则分数排序后的完整岗位对比结论。"""

    recommended_job_id: int = Field(gt=0)
    recommended_job: str
    comparisons: list[JobComparisonItem]
    reason: str
