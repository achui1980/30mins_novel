"""Provider configuration + llm dispatch tests (fake mode safe)."""

from app import config


def test_provider_defaults_to_bedrock():
    assert config.LLM_PROVIDER == "bedrock"


def test_openai_compatible_defaults(monkeypatch):
    monkeypatch.setenv("NOVEL_KG_LLM_PROVIDER", "openai_compatible")
    import importlib
    importlib.reload(config)
    assert config.OPENAI_COMPATIBLE_BASE_URL == "https://api.deepseek.com"
    assert config.OPENAI_COMPATIBLE_MODEL_ID == "deepseek-v4-flash"
    assert config.OPENAI_COMPATIBLE_THINKING is False
    assert config.OPENAI_COMPATIBLE_MAX_TOKENS == 8192


def test_thinking_flag_true(monkeypatch):
    monkeypatch.setenv("NOVEL_KG_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("NOVEL_KG_OPENAI_COMPATIBLE_THINKING", "1")
    import importlib
    importlib.reload(config)
    assert config.OPENAI_COMPATIBLE_THINKING is True
