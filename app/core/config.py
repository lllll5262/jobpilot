"""应用配置。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量和项目根目录的 .env 文件加载配置。"""

    app_name: str = "JobPilot"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

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
