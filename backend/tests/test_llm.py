"""Provider configuration + llm dispatch tests (fake mode safe)."""

from app import config


def test_provider_defaults_to_bedrock():
    assert config.LLM_PROVIDER == "bedrock"


def test_openai_compatible_defaults(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai_compatible")
    monkeypatch.setattr(config, "OPENAI_COMPATIBLE_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setattr(config, "OPENAI_COMPATIBLE_MODEL_ID", "deepseek-v4-flash")
    monkeypatch.setattr(config, "OPENAI_COMPATIBLE_THINKING", False)
    monkeypatch.setattr(config, "OPENAI_COMPATIBLE_MAX_TOKENS", 8192)
    assert config.OPENAI_COMPATIBLE_BASE_URL == "https://api.deepseek.com"
    assert config.OPENAI_COMPATIBLE_MODEL_ID == "deepseek-v4-flash"
    assert config.OPENAI_COMPATIBLE_THINKING is False
    assert config.OPENAI_COMPATIBLE_MAX_TOKENS == 8192


def test_thinking_flag_true(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai_compatible")
    monkeypatch.setattr(config, "OPENAI_COMPATIBLE_THINKING", True)
    assert config.OPENAI_COMPATIBLE_THINKING is True
