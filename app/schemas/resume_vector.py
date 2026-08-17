"""简历向量检索相关 Schema。"""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.resume import ResumeParseResult


class ResumeVectorModel(BaseModel):
    """简历向量接口的公共严格配置。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResumeSearchRequest(ResumeVectorModel):
    """在指定简历中检索与问题最相关的原文片段。"""

    query: str = Field(min_length=1, max_length=2_000)
    resume_id: int | None = Field(default=None, gt=0)
    limit: int | None = Field(default=None, ge=1, le=50)


class ResumeChunkMatch(ResumeVectorModel):
    """Milvus 混合检索返回的父子块及排序分数。"""

    resume_id: int
    doc_hash: str
    parent_id: str
    chunk_id: str
    text: str
    parent_content: str
    score: float


class ResumeSearchResult(ResumeVectorModel):
    """简历语义检索结果。"""

    query: str
    matches: list[ResumeChunkMatch]


class ResumeSourceRecord(ResumeVectorModel):
    """MinIO 原始文件的元数据、短时下载地址和结构化结果。"""

    resume_id: int
    user_id: int
    filename: str
    doc_hash: str
    file_size_bytes: int
    content_type: str
    storage_uri: str
    download_url: str
    resume: ResumeParseResult
