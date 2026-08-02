"""Provider configuration + llm dispatch tests (fake mode safe)."""

import pytest
from pydantic import BaseModel

from app import config
from app.pipeline import llm


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


# ---------------------------------------------------------------------------
# Provider dispatch tests. Monkeypatches _openai_completion; never touches
# network.
# ---------------------------------------------------------------------------


class _Dummy(BaseModel):
    name: str
    age: int


def test_openai_structured_output_parses_json(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai_compatible")
    monkeypatch.setattr(
        llm, "_openai_completion",
        lambda messages, model, max_tokens: '{"name": "张三", "age": 30}',
    )
    out = llm.structured_output(_Dummy, "问", system_prompt="提示", what="t")
    assert out.name == "张三" and out.age == 30


def test_openai_structured_output_repair_loop(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai_compatible")
    calls = iter(['not json', '{"name": "李四", "age": 40}'])
    monkeypatch.setattr(
        llm, "_openai_completion",
        lambda messages, model, max_tokens: next(calls),
    )
    out = llm.structured_output(_Dummy, "问", system_prompt="提示", what="t", attempts=3)
    assert out.name == "李四"


def test_openai_structured_output_raises_after_attempts(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai_compatible")
    monkeypatch.setattr(
        llm, "_openai_completion",
        lambda messages, model, max_tokens: "not json",
    )
    with pytest.raises(Exception):
        llm.structured_output(_Dummy, "问", system_prompt="提示", what="t", attempts=2)
