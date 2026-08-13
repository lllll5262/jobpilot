"""技能匹配规则。"""

from dataclasses import dataclass

from app.schemas.match import SemanticSkillMatch
from app.schemas.profile import SkillLevel

SKILL_LEVEL_FACTORS: dict[SkillLevel, float] = {
    SkillLevel.ADVANCED: 1.0,
    SkillLevel.INTERMEDIATE: 0.8,
    SkillLevel.BEGINNER: 0.5,
    SkillLevel.UNKNOWN: 0.0,
}


def normalize_skill(skill: str) -> str:
    """生成用于精确比较的技能键，同时保留 C++、C# 等语义字符。"""
    return "".join(
        character for character in skill.casefold() if character not in {" ", "-", "_", "."}
    )


@dataclass(frozen=True, slots=True)
class SkillEvaluation:
    """技能规则的确定性计算结果。"""

    required_ratio: float
    preferred_ratio: float
    matched_skills: list[str]
    missing_skills: list[str]


def evaluate_skills(
    *,
    required_skills: list[str],
    preferred_skills: list[str],
    candidate_skills: dict[str, SkillLevel],
    semantic_matches: list[SemanticSkillMatch],
) -> SkillEvaluation:
    """结合精确匹配和已校验语义映射，按能力等级计算覆盖率。"""
    candidate_lookup = {
        normalize_skill(skill): (skill, level) for skill, level in candidate_skills.items()
    }
    job_skills = [*required_skills, *preferred_skills]
    job_lookup = {normalize_skill(skill): skill for skill in job_skills}

    semantic_lookup: dict[str, str] = {}
    for match in semantic_matches:
        job_key = normalize_skill(match.job_skill)
        candidate_key = normalize_skill(match.candidate_skill)
        # LLM 的映射只有两端都来自真实输入时才生效。
        if job_key in job_lookup and candidate_key in candidate_lookup:
            semantic_lookup[job_key] = candidate_key

    def skill_factor(job_skill: str) -> float:
        job_key = normalize_skill(job_skill)
        candidate_key = job_key if job_key in candidate_lookup else semantic_lookup.get(job_key)
        if candidate_key is None:
            return 0.0
        return SKILL_LEVEL_FACTORS[candidate_lookup[candidate_key][1]]

    required_factors = [skill_factor(skill) for skill in required_skills]
    preferred_factors = [skill_factor(skill) for skill in preferred_skills]
    matched_skills = [skill for skill in job_skills if skill_factor(skill) > 0]
    missing_skills = [skill for skill in required_skills if skill_factor(skill) == 0]

    return SkillEvaluation(
        required_ratio=(sum(required_factors) / len(required_factors) if required_factors else 1.0),
        preferred_ratio=(
            sum(preferred_factors) / len(preferred_factors) if preferred_factors else 1.0
        ),
        matched_skills=list(dict.fromkeys(matched_skills)),
        missing_skills=missing_skills,
    )
