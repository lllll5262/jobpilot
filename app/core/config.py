"""应用配置。"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量和项目根目录的 .env 文件加载配置。"""

    app_name: str = "JobPilot"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    llm_provider: Literal["qwen", "deepseek", "glm"] = "qwen"
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    # 保留上面的通用配置以兼容已有 .env；以下配置用于前端按请求切换模型。
    qwen_api_key: SecretStr | None = None
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    glm_api_key: SecretStr | None = None
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    glm_model: str = "glm-5.2"
    resume_max_file_size_mb: int = Field(default=10, gt=0, le=50)
    resume_max_pages: int = Field(default=20, gt=0, le=100)
    resume_max_text_chars: int = Field(default=50_000, gt=0, le=200_000)
    database_url: SecretStr = SecretStr(
        "mysql+aiomysql://root:password@127.0.0.1:3306/jobpilot?charset=utf8mb4"
    )
    database_echo: bool = False
    redis_url: SecretStr = SecretStr("redis://:password@127.0.0.1:6379/0")
    celery_broker_url: SecretStr = SecretStr("redis://:password@127.0.0.1:6379/1")
    celery_result_backend: SecretStr = SecretStr("redis://:password@127.0.0.1:6379/2")
    celery_task_soft_time_limit_seconds: int = Field(default=840, ge=60, le=3_600)
    celery_task_time_limit_seconds: int = Field(default=900, ge=60, le=3_900)
    session_ttl_seconds: int = Field(default=86_400, ge=300, le=2_592_000)
    conversation_max_turns: int = Field(default=10, ge=1, le=50)
    agent_cache_ttl_seconds: int = Field(default=3_600, ge=60, le=86_400)
    checkpoint_ttl_seconds: int = Field(default=86_400, ge=300, le=2_592_000)
    # MinIO 保存原始 PDF；MySQL 只保存对象地址、校验值和业务结构化数据。
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: SecretStr = SecretStr("")
    minio_secret_key: SecretStr = SecretStr("")
    minio_secure: bool = False
    minio_region: str | None = None
    minio_resume_bucket: str = "jobpilot-resumes"
    minio_presigned_url_ttl_seconds: int = Field(default=900, ge=60, le=604_800)
    # Milvus 只保存父子分块及 BGE-M3 稠密/稀疏向量，不保存原始 PDF 二进制。
    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_token: SecretStr | None = None
    milvus_database: str = "default"
    milvus_resume_collection: str = "jobpilot_resume_chunks"
    milvus_resume_collection_version: str = Field(default="v1", pattern=r"^v[1-9]\d*$")
    milvus_resume_alias: str = "jobpilot_resume_chunks_current"
    resume_embedding_model_path: str = "models/bge-m3"
    resume_embedding_device: str = "cpu"
    resume_embedding_use_fp16: bool = False
    resume_embedding_batch_size: int = Field(default=16, ge=1, le=256)
    resume_parent_chunk_size: int = Field(default=1_000, ge=400, le=4_000)
    resume_child_chunk_size: int = Field(default=400, ge=100, le=1_500)
    resume_chunk_overlap: int = Field(default=100, ge=0, le=500)
    resume_retrieval_limit: int = Field(default=8, ge=1, le=50)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="JOBPILOT_",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """缓存配置实例，避免在请求处理中重复读取环境变量。"""
    return Settings()
