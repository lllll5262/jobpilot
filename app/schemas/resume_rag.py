"""简历检索增强问答相关 Schema。"""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.resume_vector import ResumeChunkMatch


class ResumeRagModel(BaseModel):
    """简历 RAG 接口的公共严格配置。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResumeAnswerRequest(ResumeRagModel):
    """基于指定或最新简历回答一个事实问题。"""

    query: str = Field(min_length=1, max_length=2_000)
    resume_id: int | None = Field(default=None, gt=0)
    limit: int | None = Field(default=None, ge=1, le=50)


class ResumeGroundedAnswerDraft(ResumeRagModel):
    """LLM 必须返回的有来源回答。"""

    answer: str = Field(min_length=1, max_length=8_000)
    cited_parent_ids: list[str]


class ResumeAnswerResult(ResumeRagModel):
    """检索上下文、生成答案和来源引用。"""

    query: str
    answer: str
    resume_id: int | None
    cited_parent_ids: list[str]
    contexts: list[ResumeChunkMatch]
