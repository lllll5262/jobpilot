"""API 层共享依赖。"""

from app.core.config import get_settings
from app.llm.client import OpenAICompatibleClient


def get_llm_client() -> OpenAICompatibleClient:
    """根据环境配置创建 OpenAI-compatible 客户端。"""
    settings = get_settings()
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key is not None else None
    return OpenAICompatibleClient(
        provider=settings.llm_provider,
        api_key=api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
