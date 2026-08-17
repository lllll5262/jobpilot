"""Milvus 简历存储组件的进程级生命周期。"""

from functools import lru_cache

from app.core.config import get_settings
from app.services.resume_chunking_service import ResumeChunkingService
from app.services.resume_knowledge_service import ResumeKnowledgeService
from app.vectorstore.milvus_resume_store import MilvusResumeVectorStore


@lru_cache
def get_milvus_resume_store() -> MilvusResumeVectorStore:
    """复用 Milvus 客户端和本地 BGE-M3 模型，避免每次请求重新加载。"""
    settings = get_settings()
    token = (
        settings.milvus_token.get_secret_value().strip()
        if settings.milvus_token is not None
        else ""
    )
    return MilvusResumeVectorStore(
        uri=settings.milvus_uri,
        token=token or None,
        database=settings.milvus_database,
        collection=settings.milvus_resume_collection,
        model_path=settings.resume_embedding_model_path,
        device=settings.resume_embedding_device,
        use_fp16=settings.resume_embedding_use_fp16,
    )


@lru_cache
def get_resume_knowledge_service() -> ResumeKnowledgeService:
    """组装父子分块和 Milvus 双向量存储。"""
    settings = get_settings()
    return ResumeKnowledgeService(
        chunking_service=ResumeChunkingService(
            parent_chunk_size=settings.resume_parent_chunk_size,
            child_chunk_size=settings.resume_child_chunk_size,
            chunk_overlap=settings.resume_chunk_overlap,
        ),
        vector_store=get_milvus_resume_store(),
    )


async def dispose_resume_knowledge_stores() -> None:
    """应用停止时释放 Milvus 连接和模型引用。"""
    if get_milvus_resume_store.cache_info().currsize:
        get_milvus_resume_store().close()
    get_resume_knowledge_service.cache_clear()
    get_milvus_resume_store.cache_clear()
