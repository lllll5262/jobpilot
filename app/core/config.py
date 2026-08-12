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
    llm_provider: Literal["qwen", "deepseek"] = "qwen"
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    resume_max_file_size_mb: int = Field(default=10, gt=0, le=50)
    resume_max_pages: int = Field(default=20, gt=0, le=100)
    resume_max_text_chars: int = Field(default=50_000, gt=0, le=200_000)
    database_url: SecretStr = SecretStr(
        "mysql+aiomysql://root:password@127.0.0.1:3306/jobpilot?charset=utf8mb4"
    )
    database_echo: bool = False
    redis_url: SecretStr = SecretStr("redis://:password@127.0.0.1:6379/0")
    session_ttl_seconds: int = Field(default=86_400, ge=300, le=2_592_000)
    conversation_max_turns: int = Field(default=10, ge=1, le=50)
    agent_cache_ttl_seconds: int = Field(default=3_600, ge=60, le=86_400)
    checkpoint_ttl_seconds: int = Field(default=86_400, ge=300, le=2_592_000)

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
