"""岗位匹配相关数据模型。"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.job import JDParseResult
from app.schemas.profile import CandidateProfile
from app.schemas.resume import ResumeParseResult


class ProjectRelevance(StrEnum):
    """LLM 对候选人项目与岗位相关度的语义判断。"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class ExperienceFit(StrEnum):
    """LLM 对工作或实习经验要求的语义判断。"""

    MEETS = "meets"
    PARTIAL = "partial"
    NOT_MEETS = "not_meets"
    UNKNOWN = "unknown"


class Recommendation(StrEnum):
    """由 Python 分数阈值产生的推荐结论。"""

    RECOMMEND = "RECOMMEND"
    CONSIDER = "CONSIDER"
    NOT_RECOMMEND = "NOT_RECOMMEND"


class SemanticSkillMatch(BaseModel):
    """LLM 判断出的 JD 技能与候选人技能语义等价关系。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    job_skill: str = Field(min_length=1)
    candidate_skill: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class SemanticMatchAssessment(BaseModel):
    """LLM 只负责产生的语义判断，不包含任何数值分数。"""

    model_config = ConfigDict(extra="forbid")

    semantic_skill_matches: list[SemanticSkillMatch]
    project_relevance: ProjectRelevance
    experience_fit: ExperienceFit
    strong_points: list[str]
    weak_points: list[str]

    @field_validator("strong_points", "weak_points")
    @classmethod
    def normalize_points(cls, points: list[str]) -> list[str]:
        """清理空内容并保持首次出现顺序。"""
        normalized: list[str] = []
        seen: set[str] = set()
        for point in points:
            clean_point = point.strip()
            normalized_key = clean_point.casefold()
            if clean_point and normalized_key not in seen:
                normalized.append(clean_point)
                seen.add(normalized_key)
        return normalized


class MatchRequest(BaseModel):
    """岗位匹配请求，显式组合三个独立领域对象。"""

    model_config = ConfigDict(extra="forbid")

    resume: ResumeParseResult
    profile: CandidateProfile
    job: JDParseResult


class MatchResult(BaseModel):
    """规则引擎计算后的岗位匹配结果。"""

    model_config = ConfigDict(extra="forbid")

    match_score: int = Field(ge=0, le=100)
    matched_skills: list[str]
    missing_skills: list[str]
    strong_points: list[str]
    weak_points: list[str]
    recommendation: Recommendation
