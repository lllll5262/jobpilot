"""候选人能力画像相关数据模型。"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.resume import ResumeParseResult


class SkillLevel(StrEnum):
    """基于简历证据评估的技能熟练度。"""

    ADVANCED = "advanced"
    INTERMEDIATE = "intermediate"
    BEGINNER = "beginner"
    UNKNOWN = "unknown"


class ProfileBuildRequest(BaseModel):
    """能力画像构建请求，输入必须是已解析的 Resume。"""

    model_config = ConfigDict(extra="forbid")

    resume: ResumeParseResult


class CandidateProfile(BaseModel):
    """从经历证据推导出的候选人能力画像。"""

    model_config = ConfigDict(extra="forbid")

    skills: dict[str, SkillLevel]
    domains: list[str]

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, skills: dict[str, SkillLevel]) -> dict[str, SkillLevel]:
        """清理技能名称，并按大小写不敏感方式去重。"""
        normalized: dict[str, SkillLevel] = {}
        seen: set[str] = set()
        for skill, level in skills.items():
            clean_skill = skill.strip()
            normalized_key = clean_skill.casefold()
            if clean_skill and normalized_key not in seen:
                normalized[clean_skill] = level
                seen.add(normalized_key)
        return normalized

    @field_validator("domains")
    @classmethod
    def normalize_domains(cls, domains: list[str]) -> list[str]:
        """清理空领域并保持首次出现顺序。"""
        normalized: list[str] = []
        seen: set[str] = set()
        for domain in domains:
            clean_domain = domain.strip()
            normalized_key = clean_domain.casefold()
            if clean_domain and normalized_key not in seen:
                normalized.append(clean_domain)
                seen.add(normalized_key)
        return normalized
