"""数据库持久化接口的数据模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.job import JDParseResult
from app.schemas.match import MatchResult
from app.schemas.profile import CandidateProfile
from app.schemas.resume import ResumeParseResult


class PersistenceRequest(BaseModel):
    """持久化写入请求的严格基类。"""

    model_config = ConfigDict(extra="forbid")


class UserCreateRequest(PersistenceRequest):
    """创建用户请求；阶段 5 不包含认证信息。"""

    email: str = Field(min_length=3, max_length=255)
    name: str | None = Field(default=None, max_length=100)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, email: str) -> str:
        """执行足够当前阶段使用的基础邮箱规范化。"""
        normalized = email.strip().casefold()
        if "@" not in normalized:
            raise ValueError("email must contain @")
        return normalized


class UserRecord(BaseModel):
    """用户持久化记录。"""

    id: int
    email: str
    name: str | None
    created_at: datetime


class ResumeRecord(BaseModel):
    """已保存的结构化 Resume。"""

    id: int
    user_id: int
    filename: str
    resume: ResumeParseResult
    created_at: datetime


class ProfileBuildStoredRequest(PersistenceRequest):
    """基于已保存 Resume 构建当前 Profile。"""

    resume_id: int = Field(gt=0)


class ProfileRecord(BaseModel):
    """已保存的 Candidate Profile。"""

    id: int
    user_id: int
    resume_id: int
    profile: CandidateProfile
    is_current: bool
    created_at: datetime


class JobParseStoredRequest(PersistenceRequest):
    """解析并保存 JD 的请求。"""

    jd_text: str = Field(min_length=1, max_length=20_000)

    @field_validator("jd_text")
    @classmethod
    def normalize_jd_text(cls, jd_text: str) -> str:
        """拒绝空白 JD。"""
        normalized = jd_text.strip()
        if not normalized:
            raise ValueError("jd_text must not be blank")
        return normalized


class JobRecord(BaseModel):
    """已保存的原始和结构化 JD。"""

    id: int
    user_id: int
    raw_text: str
    job: JDParseResult
    created_at: datetime


class AnalysisCreateRequest(PersistenceRequest):
    """使用当前 Profile 分析一个已保存岗位。"""

    job_id: int = Field(gt=0)


class AnalysisRecord(BaseModel):
    """已保存的岗位匹配分析。"""

    id: int
    user_id: int
    resume_id: int
    profile_id: int
    job_id: int
    result: MatchResult
    created_at: datetime
