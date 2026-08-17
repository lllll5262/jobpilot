"""MinIO 简历对象存储的进程级生命周期。"""

from functools import lru_cache

from app.core.config import get_settings
from app.storage.minio_resume_store import MinioResumeObjectStore


@lru_cache
def get_resume_object_store() -> MinioResumeObjectStore:
    """复用 MinIO 客户端，并保持 bucket 初始化幂等。"""
    settings = get_settings()
    return MinioResumeObjectStore(
        endpoint=settings.minio_endpoint.strip(),
        access_key=settings.minio_access_key.get_secret_value().strip(),
        secret_key=settings.minio_secret_key.get_secret_value().strip(),
        secure=settings.minio_secure,
        bucket=settings.minio_resume_bucket.strip(),
        region=(settings.minio_region or "").strip() or None,
        presigned_url_ttl_seconds=settings.minio_presigned_url_ttl_seconds,
    )


async def dispose_resume_object_store() -> None:
    """应用停止时释放 MinIO 连接池。"""
    if get_resume_object_store.cache_info().currsize:
        get_resume_object_store().close()
    get_resume_object_store.cache_clear()
