"""确定性岗位匹配算分服务。"""

from dataclasses import dataclass

from app.rules.education_rules import EducationFit
from app.rules.scoring_rules import (
    EDUCATION_FACTORS,
    EDUCATION_WEIGHT,
    EXPERIENCE_FACTORS,
    EXPERIENCE_WEIGHT,
    PREFERRED_SKILL_WEIGHT,
    PROJECT_FACTORS,
    PROJECT_WEIGHT,
    SKILL_WEIGHT,
    recommendation_for_score,
)
from app.schemas.match import ExperienceFit, ProjectRelevance, Recommendation


@dataclass(frozen=True, slots=True)
class ScoreInput:
    """规则引擎所需的标准化因子。"""

    required_skill_ratio: float
    preferred_skill_ratio: float
    project_relevance: ProjectRelevance
    experience_fit: ExperienceFit
    education_fit: EducationFit
    experience_required: bool


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """最终整数分和推荐结论。"""

    score: int
    recommendation: Recommendation


class ScoringService:
    """按照固定权重计算分数，完全不依赖 LLM 自由打分。"""

    def calculate(self, score_input: ScoreInput) -> ScoreResult:
        """计算 0-100 分，并通过固定阈值生成推荐结论。"""
        experience_factor = (
            EXPERIENCE_FACTORS[score_input.experience_fit]
            if score_input.experience_required
            else 1.0
        )
        raw_score = (
            score_input.required_skill_ratio * SKILL_WEIGHT
            + PROJECT_FACTORS[score_input.project_relevance] * PROJECT_WEIGHT
            + experience_factor * EXPERIENCE_WEIGHT
            + EDUCATION_FACTORS[score_input.education_fit] * EDUCATION_WEIGHT
            + score_input.preferred_skill_ratio * PREFERRED_SKILL_WEIGHT
        )
        score = max(0, min(100, round(raw_score)))
        return ScoreResult(
            score=score,
            recommendation=recommendation_for_score(score),
        )
