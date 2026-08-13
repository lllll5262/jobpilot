"""简历解析相关数据模型。"""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResumeModel(BaseModel):
    """简历 Schema 的公共严格配置。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PersonalInformation(ResumeModel):
    """候选人基本信息。"""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None


class EducationExperience(ResumeModel):
    """教育经历。"""

    school: str = Field(min_length=1)
    degree: str | None = None
    major: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class ProjectExperience(ResumeModel):
    """项目经历。"""

    name: str = Field(min_length=1)
    role: str | None = None
    description: str | None = None
    technologies: list[str]
    start_date: str | None = None
    end_date: str | None = None


class InternshipExperience(ResumeModel):
    """实习经历。"""

    company: str = Field(min_length=1)
    position: str | None = None
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class Certificate(ResumeModel):
    """证书或认证。"""

    name: str = Field(min_length=1)
    issuer: str | None = None
    date: str | None = None


class ResumeParseResult(ResumeModel):
    """LLM 输出并经 Pydantic 校验后的完整简历结构。"""

    personal_info: PersonalInformation
    education: list[EducationExperience]
    skills: list[str]
    projects: list[ProjectExperience]
    internships: list[InternshipExperience]
    certificates: list[Certificate]

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, skills: list[str]) -> list[str]:
        """清理空技能并按首次出现顺序去重。"""
        normalized: list[str] = []
        seen: set[str] = set()
        for skill in skills:
            clean_skill = skill.strip()
            if clean_skill and clean_skill.casefold() not in seen:
                normalized.append(clean_skill)
                seen.add(clean_skill.casefold())
        return normalized
