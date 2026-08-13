"""JD 解析相关数据模型。"""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JDParseRequest(BaseModel):
    """JD 解析请求。"""

    jd_text: str = Field(min_length=1, max_length=20_000, description="原始职位描述文本")

    @field_validator("jd_text")
    @classmethod
    def validate_jd_text(cls, value: str) -> str:
        """拒绝只包含空白字符的 JD。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("jd_text must not be blank")
        return normalized


class JDParseResult(BaseModel):
    """大模型从 JD 中提取的结构化信息。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    job_title: str = Field(min_length=1, description="职位名称")
    required_skills: list[str] = Field(description="明确要求掌握的技能")
    preferred_skills: list[str] = Field(description="优先、加分或非必需技能")
    education: str | None = Field(description="学历要求，未提及时为 null")
    experience: str | None = Field(description="工作或实习经验要求，未提及时为 null")

    @field_validator("required_skills", "preferred_skills")
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
