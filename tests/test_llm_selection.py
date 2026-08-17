"""按请求切换 LLM 供应商的配置测试。"""

from pydantic import SecretStr

from app.api import dependencies
from app.core.config import Settings


def build_settings() -> Settings:
    """构造不读取开发机凭据的三供应商测试配置。"""
    return Settings(
        _env_file=None,
        llm_provider="qwen",
        llm_api_key=SecretStr("legacy-qwen-key"),
        llm_base_url="https://legacy-qwen.example/v1",
        llm_model="legacy-qwen",
        deepseek_api_key=SecretStr("deepseek-key"),
        deepseek_base_url="https://deepseek.example/v1",
        deepseek_model="deepseek-test",
        glm_api_key=SecretStr("glm-key"),
        glm_base_url="https://glm.example/v1",
        glm_model="glm-test",
    )


def test_default_model_remains_backward_compatible(monkeypatch) -> None:
    """未发送请求头时继续使用已有 JOBPILOT_LLM_* 配置。"""
    monkeypatch.setattr(dependencies, "get_settings", build_settings)

    client = dependencies.get_llm_client()

    assert client.provider == "qwen"
    assert client.model == "legacy-qwen"
    assert client.is_configured is True


def test_blank_provider_key_still_uses_legacy_default(monkeypatch) -> None:
    """从示例文件复制出的空 Qwen Key 不能屏蔽旧版有效配置。"""
    settings = build_settings()
    settings.qwen_api_key = SecretStr("")
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)

    client = dependencies.get_llm_client("qwen")

    assert client.provider == "qwen"
    assert client.model == "legacy-qwen"
    assert client.is_configured is True


def test_request_header_selects_glm(monkeypatch) -> None:
    """X-LLM-Provider 应切换完整连接配置，而不只替换模型名称。"""
    monkeypatch.setattr(dependencies, "get_settings", build_settings)

    client = dependencies.get_llm_client("glm")

    assert client.provider == "glm"
    assert client.model == "glm-test"


def test_request_header_selects_deepseek(monkeypatch) -> None:
    """DeepSeek 使用自己的配置，不复用 Qwen API Key。"""
    monkeypatch.setattr(dependencies, "get_settings", build_settings)

    client = dependencies.get_llm_client("deepseek")

    assert client.provider == "deepseek"
    assert client.model == "deepseek-test"
