"""岗位匹配权重与阈值规则。"""

from app.rules.education_rules import EducationFit
from app.schemas.match import ExperienceFit, ProjectRelevance, Recommendation

SKILL_WEIGHT = 40
PROJECT_WEIGHT = 25
EXPERIENCE_WEIGHT = 15
EDUCATION_WEIGHT = 10
PREFERRED_SKILL_WEIGHT = 10

PROJECT_FACTORS: dict[ProjectRelevance, float] = {
    ProjectRelevance.HIGH: 1.0,
    ProjectRelevance.MEDIUM: 0.7,
    ProjectRelevance.LOW: 0.3,
    ProjectRelevance.NONE: 0.0,
}

EXPERIENCE_FACTORS: dict[ExperienceFit, float] = {
    ExperienceFit.MEETS: 1.0,
    ExperienceFit.PARTIAL: 0.6,
    ExperienceFit.NOT_MEETS: 0.0,
    ExperienceFit.UNKNOWN: 0.4,
}

EDUCATION_FACTORS: dict[EducationFit, float] = {
    EducationFit.NOT_REQUIRED: 1.0,
    EducationFit.MEETS: 1.0,
    EducationFit.NOT_MEETS: 0.0,
    EducationFit.UNKNOWN: 0.5,
}


def recommendation_for_score(score: int) -> Recommendation:
    """使用固定阈值生成推荐结论。"""
    if score >= 80:
        return Recommendation.RECOMMEND
    if score >= 60:
        return Recommendation.CONSIDER
    return Recommendation.NOT_RECOMMEND
