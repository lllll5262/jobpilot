"""API 层共享依赖。"""

from typing import Annotated

from fastapi import Depends, Header

from app.core.config import Settings, get_settings
from app.llm.client import LLMProvider, OpenAICompatibleClient
from app.parsers.pdf_parser import PDFParser
from app.services.resume_parser_service import ResumeParserService


def get_llm_client(
    selected_provider: Annotated[
        LLMProvider | None,
        Header(alias="X-LLM-Provider"),
    ] = None,
) -> OpenAICompatibleClient:
    """根据请求头选择模型；未传请求头时继续使用默认模型配置。"""
    settings = get_settings()
    provider = selected_provider or settings.llm_provider
    provider_api_key = getattr(settings, f"{provider}_api_key")
    # 旧项目只有 JOBPILOT_LLM_*。当前选择等于默认供应商时继续兼容旧配置。
    uses_provider_config = bool(
        provider_api_key is not None and provider_api_key.get_secret_value().strip()
    )
    api_key_setting = (
        provider_api_key
        if uses_provider_config
        else (settings.llm_api_key if provider == settings.llm_provider else None)
    )
    api_key = api_key_setting.get_secret_value() if api_key_setting is not None else None
    base_url = getattr(settings, f"{provider}_base_url")
    model = getattr(settings, f"{provider}_model")
    if provider == settings.llm_provider and not uses_provider_config:
        # 显式配置的旧字段优先，确保现有部署升级后行为不变。
        base_url = settings.llm_base_url or base_url
        model = settings.llm_model or model
    return OpenAICompatibleClient(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def get_resume_parser_service(
    client: Annotated[OpenAICompatibleClient, Depends(get_llm_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ResumeParserService:
    """组装持久化上传流程使用的 PDF 简历解析服务。"""
    return ResumeParserService(
        PDFParser(max_pages=settings.resume_max_pages),
        client,
        max_text_chars=settings.resume_max_text_chars,
    )
