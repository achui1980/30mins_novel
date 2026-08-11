"""LLM provider abstraction (multi-model support).

Single place that touches ``strands`` / ``openai``. Provider selected by
``config.LLM_PROVIDER``:

- ``bedrock``: strands ``Agent`` + ``BedrockModel`` (original behavior).
- ``openai_compatible``: strands ``Agent`` + ``OpenAIModel`` pointed at any
  OpenAI-compatible endpoint (DeepSeek, Kimi, vLLM, ...).

``structured_output`` is dispatched per-provider because DeepSeek rejects
OpenAI's ``response_format={"type": "json_schema"}`` with HTTP 400; the OpenAI
path uses ``{"type": "json_object"}`` plus client-side pydantic validation with
a repair/retry loop instead.
"""

from __future__ import annotations

import json
import logging
import re
import time

from pydantic import ValidationError

from .. import config

logger = logging.getLogger("novel_kg.llm")

# Model-id prefixes/substrings whose OpenAI-compatible endpoint accepts the
# `extra_body={"thinking": {"type": "disabled"}}` param. Both DeepSeek and
# MiniMax support this shape; unrelated endpoints may 400 on unknown
# extra_body fields, so the toggle is only sent to known-compatible models.
_THINKING_TOGGLE_MARKERS = ("deepseek", "minimax")

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _schema_json(schema) -> str:
    """Serialize a pydantic model's JSON schema for embedding into prompts.

    The OpenAI-compatible path has no server-side json_schema enforcement
    (DeepSeek rejects it), so the schema must be shown to the model in the
    prompt text, otherwise small models invent field names (e.g. `name` for
    `summary`, `character1` for `source`).
    """
    return json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)


def _supports_thinking_toggle(model_id: str | None = None) -> bool:
    """True when the model id belongs to a family that supports the
    ``thinking`` extra_body toggle (DeepSeek, MiniMax).

    Falls back to the fast model when called without an explicit id, keeping
    the historical default behavior.
    """
    resolved = (model_id or config.OPENAI_COMPATIBLE_MODEL_ID).lower()
    return any(marker in resolved for marker in _THINKING_TOGGLE_MARKERS)


def _clean_llm_json_text(text: str) -> str:
    """Strip ``<think>...</think>`` reasoning blocks and markdown code fences.

    Some OpenAI-compatible models (e.g. MiniMax-M3 with thinking left on)
    prepend a ``<think>...</think>`` block to the answer and/or wrap the JSON
    payload in a ` ```json ` fenced code block instead of emitting raw JSON.
    Neither is valid JSON on its own, so strip both before validation.
    """
    cleaned = _THINK_BLOCK_RE.sub("", text).strip()
    fence_match = _CODE_FENCE_RE.match(cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    return cleaned


# ---------------------------------------------------------------------------
# Model / agent construction
# ---------------------------------------------------------------------------


def _resolve_provider(tier: str) -> str:
    """Provider for a tier: the strong provider for 'strong', else the default."""
    return config.STRONG_LLM_PROVIDER if tier == "strong" else config.LLM_PROVIDER


def _resolve_model_id(tier: str) -> str:
    """Model id for a tier: strong model for 'strong', else the provider default.

    The strong model id never leaks into the fast tier.
    """
    provider = _resolve_provider(tier)
    default = (
        config.OPENAI_COMPATIBLE_MODEL_ID
        if provider == "openai_compatible"
        else config.BEDROCK_MODEL_ID
    )
    if tier == "strong":
        return config.STRONG_MODEL_ID or default
    return default


def make_model(tier: str = "fast"):  # pragma: no cover - requires LLM creds
    """Return the strands model instance for the configured provider."""
    provider = _resolve_provider(tier)
    model_id = _resolve_model_id(tier)
    if provider == "openai_compatible":
        from strands.models.openai import OpenAIModel

        params: dict = {}
        # The `thinking` field is only supported by DeepSeek/MiniMax; other
        # endpoints may 400 on unknown extra_body fields.
        if not config.OPENAI_COMPATIBLE_THINKING and _supports_thinking_toggle(model_id):
            params["extra_body"] = {"thinking": {"type": "disabled"}}
        return OpenAIModel(
            client_args={
                "api_key": config.OPENAI_COMPATIBLE_API_KEY,
                "base_url": config.OPENAI_COMPATIBLE_BASE_URL,
                "timeout": config.OPENAI_COMPATIBLE_TIMEOUT,
            },
            model_id=model_id,
            params=params,
        )
    from strands.models import BedrockModel

    from botocore.config import Config as BotocoreConfig

    return BedrockModel(
        model_id=model_id,
        region_name=config.BEDROCK_REGION,
        boto_client_config=BotocoreConfig(
            read_timeout=config.BEDROCK_TIMEOUT,
            connect_timeout=config.BEDROCK_TIMEOUT,
        ),
    )


def make_agent(system_prompt: str, tools=None, tier: str = "fast"):  # pragma: no cover - requires LLM creds
    """Return a strands Agent bound to the configured provider model."""
    from strands import Agent

    return Agent(model=make_model(tier=tier), system_prompt=system_prompt, tools=tools)


# ---------------------------------------------------------------------------
# Structured output (provider-dispatched)
# ---------------------------------------------------------------------------


def structured_output(
    schema,
    prompt: str,
    *,
    system_prompt: str,
    what: str = "",
    attempts: int = 3,
    tier: str = "fast",
):
    """Return ``schema`` parsed from the LLM, provider-agnostic."""
    if _resolve_provider(tier) == "openai_compatible":
        return _openai_structured_output(
            schema, prompt, system_prompt=system_prompt, what=what, attempts=attempts, tier=tier
        )
    return _bedrock_structured_output(
        schema, prompt, system_prompt=system_prompt, what=what, attempts=attempts, tier=tier
    )


def _bedrock_structured_output(schema, prompt, *, system_prompt, what, attempts, tier="fast"):  # pragma: no cover - AWS
    """strands agent.structured_output with retry (moved from summarize.py)."""
    agent = make_agent(system_prompt or "", tier=tier)
    last_exc = None
    for attempt in range(attempts):
        try:
            return agent.structured_output(schema, prompt)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "structured_output(%s) attempt %d/%d failed: %s",
                what, attempt + 1, attempts, exc,
            )
            if attempt < attempts - 1:
                time.sleep(config.EXTRACT_BACKOFF_BASE ** (attempt + 1))
    raise last_exc


def _openai_structured_output(schema, prompt, *, system_prompt, what, attempts, tier="fast"):
    """JSON-object structured output for OpenAI-compatible endpoints.

    DeepSeek rejects OpenAI's ``json_schema`` response_format (HTTP 400), so we
    use ``json_object`` and validate client-side with pydantic. On a parse
    failure (``ValidationError``) we append the parse error and re-prompt (a
    repair loop); on a transport/other error we just retry with the unchanged
    messages.
    """
    messages = [
        {"role": "system", "content": system_prompt or ""},
        {
            "role": "user",
            "content": (
                prompt
                + "\n只输出JSON，不要输出其他内容。"
                + "\n\n必须严格按照以下 JSON Schema 输出：\n"
                + _schema_json(schema)
            ),
        },
    ]
    last_exc = None
    for attempt in range(attempts):
        try:
            content = _openai_completion(
                messages,
                model=_resolve_model_id(tier),
                max_tokens=config.OPENAI_COMPATIBLE_MAX_TOKENS,
            )
            return schema.model_validate_json(_clean_llm_json_text(content))
        except ValidationError as exc:
            last_exc = exc
            logger.warning(
                "structured_output(%s) attempt %d/%d failed: %s",
                what, attempt + 1, attempts, exc,
            )
            if attempt < attempts - 1:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"上次输出无法解析：{exc}\n"
                            "请严格按照上述 JSON Schema 重新输出，字段名一个都不能改。"
                        ),
                    }
                )
                time.sleep(config.EXTRACT_BACKOFF_BASE ** (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "structured_output(%s) attempt %d/%d failed: %s",
                what, attempt + 1, attempts, exc,
            )
            if attempt < attempts - 1:
                time.sleep(config.EXTRACT_BACKOFF_BASE ** (attempt + 1))
    raise last_exc


def _openai_completion(messages, *, model: str, max_tokens: int):  # pragma: no cover - real call
    """Single OpenAI-compatible chat completion returning raw JSON text."""
    from openai import OpenAI

    client = OpenAI(
        api_key=config.OPENAI_COMPATIBLE_API_KEY,
        base_url=config.OPENAI_COMPATIBLE_BASE_URL,
        timeout=config.OPENAI_COMPATIBLE_TIMEOUT,
    )
    extra: dict = {}
    # The `thinking` field is only supported by DeepSeek/MiniMax; other
    # endpoints may 400 on unknown extra_body fields.
    if not config.OPENAI_COMPATIBLE_THINKING and _supports_thinking_toggle(model):
        extra["extra_body"] = {"thinking": {"type": "disabled"}}
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
        **extra,
    )
    return (resp.choices[0].message.content or "").strip()
