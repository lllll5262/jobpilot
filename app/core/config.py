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
