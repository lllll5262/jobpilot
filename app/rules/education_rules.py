"""学历匹配规则。"""

from enum import StrEnum

from app.schemas.resume import EducationExperience


class EducationFit(StrEnum):
    """学历规则判断结果。"""

    NOT_REQUIRED = "not_required"
    MEETS = "meets"
    NOT_MEETS = "not_meets"
    UNKNOWN = "unknown"


EDUCATION_KEYWORDS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (5, ("博士", "phd", "doctor")),
    (4, ("硕士", "研究生", "master")),
    (3, ("本科", "学士", "bachelor")),
    (2, ("大专", "专科", "associate")),
    (1, ("高中", "中专", "high school")),
)


def _education_rank(text: str | None) -> int | None:
    """从中英文学历文本中提取可比较等级。"""
    if not text:
        return None
    normalized = text.casefold()
    for rank, keywords in EDUCATION_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return rank
    return None


def evaluate_education(
    required_education: str | None,
    candidate_education: list[EducationExperience],
) -> EducationFit:
    """比较 JD 学历要求和候选人最高学历。"""
    if not required_education:
        return EducationFit.NOT_REQUIRED

    required_rank = _education_rank(required_education)
    candidate_ranks = [
        rank
        for education in candidate_education
        if (rank := _education_rank(education.degree)) is not None
    ]
    if required_rank is None or not candidate_ranks:
        return EducationFit.UNKNOWN
    if max(candidate_ranks) >= required_rank:
        return EducationFit.MEETS
    return EducationFit.NOT_MEETS
