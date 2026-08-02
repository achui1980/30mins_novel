# 多模型接入（通用 OpenAI 兼容 provider，首发 DeepSeek）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过全局配置（`NOVEL_KG_LLM_PROVIDER`）在 Bedrock 与任意 OpenAI 兼容端点（首发 DeepSeek）之间切换，不动 fake 离线镜像。

**Architecture:** 新增 `backend/app/pipeline/llm.py` 作为唯一 provider 抽象层：`make_agent()`（agentic 问答用）+ `structured_output()`（抽取/摘要用，按 provider 分派）。Bedrock 沿用 strands `agent.structured_output`；OpenAI 兼容端点用 `response_format=json_object` + pydantic 校验 + 修复重试（因为 DeepSeek 拒绝 `json_schema`）。

**Tech Stack:** Python 3.11+, strands (Agent/BedrockModel/OpenAIModel), openai SDK (transitive dep, 显式声明), pydantic v2, FastAPI, pytest (fake 模式)。

**Config contract (env, prefix `NOVEL_KG_`):**
| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `NOVEL_KG_LLM_PROVIDER` | `bedrock` / `openai_compatible` | `bedrock` |
| `NOVEL_KG_OPENAI_COMPATIBLE_BASE_URL` | OpenAI 兼容 base_url | `https://api.deepseek.com` |
| `NOVEL_KG_OPENAI_COMPATIBLE_API_KEY` | API key | 空 |
| `NOVEL_KG_OPENAI_COMPATIBLE_MODEL_ID` | 模型 id | `deepseek-v4-flash` |
| `NOVEL_KG_OPENAI_COMPATIBLE_THINKING` | `1`=开 thinking | `0`（默认关闭） |
| `NOVEL_KG_OPENAI_COMPATIBLE_MAX_TOKENS` | JSON 模式 max_tokens | `8192` |

---

## File Structure

- **Create** `backend/app/pipeline/llm.py` — provider 工厂 + 分派式 `structured_output`（唯一 import strands/openai 的模块）
- **Create** `backend/tests/test_llm.py` — provider 分派 + openai JSON 修复循环（monkeypatch `_openai_completion`，不触网）
- **Modify** `backend/app/config.py:67-76` — 新增上面 6 个配置项
- **Modify** `backend/app/pipeline/extract.py` — `_make_agent`/`_extract_block_sync` → `llm.structured_output`
- **Modify** `backend/app/pipeline/summarize.py` — 删 `_make_summary_agent`/`_structured_with_retry`，5 处调用改走 `llm.structured_output`
- **Modify** `backend/app/pipeline/ask.py:76-86,175-176` — `BedrockModel` → `llm.make_agent`
- **Modify** `backend/pyproject.toml:14` — 显式加 `openai>=1.40`
- **Modify** `README.md:108-116` — 配置表 + DeepSeek 接入示例

---

### Task 1: config.py 新增 provider 配置

**Files:**
- Modify: `backend/app/config.py:67-76`
- Test: `backend/tests/test_llm.py`

- [ ] **Step 1: 写失败测试** — 新建 `backend/tests/test_llm.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_llm.py -q`
Expected: FAIL（`AttributeError: module 'app.config' has no attribute 'LLM_PROVIDER'`）

- [ ] **Step 3: 实现配置** — 在 `config.py` Bedrock 段之后追加：

```python
# --- LLM provider (multi-model) ------------------------------------------
# "bedrock" keeps the original AWS Strands path; "openai_compatible" points at
# any OpenAI-compatible endpoint (DeepSeek, Kimi, vLLM, ...) via strands'
# OpenAIModel. Structured output on that path uses json_object + client-side
# pydantic validation (DeepSeek rejects OpenAI's json_schema response_format).
LLM_PROVIDER = _env("NOVEL_KG_LLM_PROVIDER", "bedrock")
OPENAI_COMPATIBLE_BASE_URL = _env(
    "NOVEL_KG_OPENAI_COMPATIBLE_BASE_URL", "https://api.deepseek.com"
)
OPENAI_COMPATIBLE_API_KEY = _env("NOVEL_KG_OPENAI_COMPATIBLE_API_KEY", "")
OPENAI_COMPATIBLE_MODEL_ID = _env(
    "NOVEL_KG_OPENAI_COMPATIBLE_MODEL_ID", "deepseek-v4-flash"
)
# DeepSeek V4 defaults to "thinking" mode (slower/costlier). Default OFF.
OPENAI_COMPATIBLE_THINKING = (
    _env("NOVEL_KG_OPENAI_COMPATIBLE_THINKING", "0") in {"1", "true", "True", "yes"}
)
OPENAI_COMPATIBLE_MAX_TOKENS = int(
    _env("NOVEL_KG_OPENAI_COMPATIBLE_MAX_TOKENS", "8192")
)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_llm.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_llm.py
git commit -m "feat: add LLM provider config (bedrock / openai_compatible)"
```

---

### Task 2: `backend/app/pipeline/llm.py` — provider 抽象层

**Files:**
- Create: `backend/app/pipeline/llm.py`
- Test: `backend/tests/test_llm.py`

- [ ] **Step 1: 写失败测试** — 追加到 `test_llm.py`：

```python
"""Provider dispatch tests. Monkeypatches _openai_completion; never touches network."""

from pydantic import BaseModel

from app import config
from app.pipeline import llm


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
    import pytest
    with pytest.raises(Exception):
        llm.structured_output(_Dummy, "问", system_prompt="提示", what="t", attempts=2)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_llm.py -q`
Expected: FAIL（`ModuleNotFoundError: app.pipeline.llm`）

- [ ] **Step 3: 实现 `llm.py`**

```python
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

import logging
import time

from .. import config

logger = logging.getLogger("novel_kg.llm")


# ---------------------------------------------------------------------------
# Model / agent construction
# ---------------------------------------------------------------------------


def make_model():  # pragma: no cover - requires LLM creds
    """Return the strands model instance for the configured provider."""
    if config.LLM_PROVIDER == "openai_compatible":
        from strands.models.openai import OpenAIModel

        params: dict = {}
        if not config.OPENAI_COMPATIBLE_THINKING:
            params["extra_body"] = {"thinking": {"type": "disabled"}}
        return OpenAIModel(
            client_args={
                "api_key": config.OPENAI_COMPATIBLE_API_KEY,
                "base_url": config.OPENAI_COMPATIBLE_BASE_URL,
            },
            model_id=config.OPENAI_COMPATIBLE_MODEL_ID,
            params=params,
        )
    from strands.models import BedrockModel

    return BedrockModel(model_id=config.BEDROCK_MODEL_ID, region_name=config.BEDROCK_REGION)


def make_agent(system_prompt: str, tools=None):  # pragma: no cover - requires LLM creds
    """Return a strands Agent bound to the configured provider model."""
    from strands import Agent

    return Agent(model=make_model(), system_prompt=system_prompt, tools=tools)


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
):
    """Return ``schema`` parsed from the LLM, provider-agnostic."""
    if config.LLM_PROVIDER == "openai_compatible":
        return _openai_structured_output(
            schema, prompt, system_prompt=system_prompt, what=what, attempts=attempts
        )
    return _bedrock_structured_output(
        schema, prompt, system_prompt=system_prompt, what=what, attempts=attempts
    )


def _bedrock_structured_output(schema, prompt, *, system_prompt, what, attempts):  # pragma: no cover - AWS
    """strands agent.structured_output with retry (moved from summarize.py)."""
    agent = make_agent(system_prompt or "")
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


def _openai_structured_output(schema, prompt, *, system_prompt, what, attempts):  # pragma: no cover - real call
    """JSON-object structured output for OpenAI-compatible endpoints.

    DeepSeek rejects OpenAI's ``json_schema`` response_format (HTTP 400), so we
    use ``json_object`` and validate client-side with pydantic. On failure we
    append the parse error and re-prompt (a repair loop).
    """
    messages = [
        {"role": "system", "content": system_prompt or ""},
        {"role": "user", "content": prompt + "\n只输出JSON，不要输出其他内容。"},
    ]
    last_exc = None
    for attempt in range(attempts):
        try:
            content = _openai_completion(
                messages,
                model=config.OPENAI_COMPATIBLE_MODEL_ID,
                max_tokens=config.OPENAI_COMPATIBLE_MAX_TOKENS,
            )
            return schema.model_validate_json(content)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "structured_output(%s) attempt %d/%d failed: %s",
                what, attempt + 1, attempts, exc,
            )
            if attempt < attempts - 1:
                messages.append(
                    {"role": "user", "content": f"上次输出无法解析：{exc}\n请重新输出符合 schema 的 JSON。"}
                )
                time.sleep(config.EXTRACT_BACKOFF_BASE ** (attempt + 1))
    raise last_exc


def _openai_completion(messages, *, model: str, max_tokens: int):  # pragma: no cover - real call
    """Single OpenAI-compatible chat completion returning raw JSON text."""
    from openai import OpenAI

    client = OpenAI(
        api_key=config.OPENAI_COMPATIBLE_API_KEY,
        base_url=config.OPENAI_COMPATIBLE_BASE_URL,
    )
    extra: dict = {}
    if not config.OPENAI_COMPATIBLE_THINKING:
        extra["extra_body"] = {"thinking": {"type": "disabled"}}
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
        **extra,
    )
    return (resp.choices[0].message.content or "").strip()
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_llm.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/llm.py backend/tests/test_llm.py
git commit -m "feat: add provider abstraction with openai_compatible structured output"
```

---

### Task 3: extract.py 改走 llm 层

**Files:**
- Modify: `backend/app/pipeline/extract.py:62-72,176-191`

- [ ] **Step 1: 改写 `_make_agent` + `_extract_block_sync`**

```python
def _extract_block_sync(prompt: str) -> ChunkExtraction:  # pragma: no cover - requires LLM creds
    """Blocking structured extraction, provider-agnostic."""
    from .. import llm

    return llm.structured_output(
        ChunkExtraction, prompt, system_prompt=SYSTEM_PROMPT, what="ChunkExtraction"
    )
```

- [ ] **Step 2: 改 `extract_blocks`（去掉 agent 构建）**

`extract.py:176-191` 改为：

```python
    use_fake = config.USE_FAKE_LLM

    sem = asyncio.Semaphore(config.EXTRACT_CONCURRENCY)
    processed = 0

    async def run_block(block: Block, known: str) -> ChunkExtraction | None:
        async with sem:
            for attempt in range(config.EXTRACT_MAX_RETRIES):
                try:
                    if use_fake:
                        return fake_extract_block(block)
                    prompt = _build_prompt(block, known, granularity)
                    return await asyncio.to_thread(_extract_block_sync, prompt)
                except Exception as exc:  # noqa: BLE001
                    if attempt == config.EXTRACT_MAX_RETRIES - 1:
                        if warn_cb:
                            warn_cb(f"块 {block.block_id} 抽取失败，已跳过: {exc}")
                        return None
                    await asyncio.sleep(config.EXTRACT_BACKOFF_BASE ** attempt)
        return None
```

- [ ] **Step 3: 同步模块 docstring**（`extract.py:3-9`）把 "AWS Strands … Bedrock" 改为 "strands（见 pipeline.llm，支持 Bedrock 与 OpenAI 兼容端点）"。

- [ ] **Step 4: 运行全量测试确认无回归**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: PASS（fake 路径未变）

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/extract.py
git commit -m "refactor: route extraction through pipeline.llm provider layer"
```

---

### Task 4: summarize.py 改走 llm 层

**Files:**
- Modify: `backend/app/pipeline/summarize.py:146-175,249-265,301-332,400-424,423-490`

- [ ] **Step 1: 删除 `_make_summary_agent` 与 `_structured_with_retry`（146-175 行），改用一个 import**（文件顶部 `from .. import config` 旁追加）：

```python
from .. import config, llm
```

- [ ] **Step 2: `_story_spine(agent, digest, title)` → `_story_spine(digest, title)`**（178 行起）：去掉 `agent` 参数，`_structured_with_retry(agent, StorySpine, prompt, what="StorySpine")` 换成：

```python
spine = llm.structured_output(StorySpine, prompt, system_prompt=SUMMARY_SYSTEM_PROMPT, what="StorySpine")
```

- [ ] **Step 3: `_llm_chapter_summary`**（249-265）：删 `agent = _make_summary_agent()`，`_structured_with_retry(agent, ChapterBrief, prompt, what="ChapterBrief")` → `llm.structured_output(ChapterBrief, prompt, system_prompt=SUMMARY_SYSTEM_PROMPT, what="ChapterBrief")`

- [ ] **Step 4: `_llm_beat_story`**（301-332）：`_structured_with_retry(_make_summary_agent(), BeatStory, prompt, what="BeatStory")` → `llm.structured_output(BeatStory, prompt, system_prompt=SUMMARY_SYSTEM_PROMPT, what="BeatStory")`

- [ ] **Step 5: `_llm_labels`**（400-420）：删 `agent = _make_summary_agent()`，`result = agent.structured_output(CommunityLabels, prompt)` → `result = llm.structured_output(CommunityLabels, prompt, system_prompt=SUMMARY_SYSTEM_PROMPT, what="CommunityLabels")`

- [ ] **Step 6: `_llm_summary`**（423-490）：删 `agent = _make_summary_agent()`；`_story_spine(agent, digest, title)` → `_story_spine(digest, title)`；`_structured_with_retry(agent, LayeredSummary, ...)` → `llm.structured_output(LayeredSummary, prompt, system_prompt=SUMMARY_SYSTEM_PROMPT, what="LayeredSummary")`；`SettingCards` 与 `SuggestedQuestionsSchema` 同样替换为 `llm.structured_output(...)`。

- [ ] **Step 7: 同步 docstring**（第 8 行）提及 multi-provider。

- [ ] **Step 8: 运行全量测试**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/pipeline/summarize.py
git commit -m "refactor: route summarization through pipeline.llm provider layer"
```

---

### Task 5: ask.py 改用 `llm.make_agent`

**Files:**
- Modify: `backend/app/pipeline/ask.py:76-86,175-176`

- [ ] **Step 1: 改 `_agent_answer_question`**：顶部 `from strands import Agent, tool` → `from strands import tool`；`from strands.models import BedrockModel` 删除；文件顶部 `from .. import config` → `from .. import config, llm`。

- [ ] **Step 2: 175-176 行替换为：**

```python
    agent = llm.make_agent(ASK_SYSTEM_PROMPT, tools=tools)
```

- [ ] **Step 3: 运行全量测试**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/pipeline/ask.py
git commit -m "refactor: route agentic Q&A through pipeline.llm provider layer"
```

---

### Task 6: 依赖声明 + README

**Files:**
- Modify: `backend/pyproject.toml:14`
- Modify: `README.md:108-116`

- [ ] **Step 1: pyproject 显式声明 openai**

`strands-agents>=0.1` 行后加：`"openai>=1.40",`

- [ ] **Step 2: README 配置表追加 6 行**（在 `NOVEL_KG_BEDROCK_REGION` 行后）：

```markdown
| `NOVEL_KG_LLM_PROVIDER` | 模型后端：`bedrock` / `openai_compatible` | `bedrock` |
| `NOVEL_KG_OPENAI_COMPATIBLE_BASE_URL` | OpenAI 兼容 base_url | `https://api.deepseek.com` |
| `NOVEL_KG_OPENAI_COMPATIBLE_API_KEY` | API key | 空 |
| `NOVEL_KG_OPENAI_COMPATIBLE_MODEL_ID` | 模型 id（如 `deepseek-v4-flash`） | `deepseek-v4-flash` |
| `NOVEL_KG_OPENAI_COMPATIBLE_THINKING` | 开启 thinking（更慢更贵） | 关闭 |
| `NOVEL_KG_OPENAI_COMPATIBLE_MAX_TOKENS` | JSON 输出长度上限 | `8192` |
```

- [ ] **Step 3: README 加一段 DeepSeek 接入示例**（离线模式段落之后）：

```markdown
### 接入 DeepSeek（OpenAI 兼容）

```bash
NOVEL_KG_LLM_PROVIDER=openai_compatible \
NOVEL_KG_OPENAI_COMPATIBLE_API_KEY=sk-xxx \
NOVEL_KG_OPENAI_COMPATIBLE_MODEL_ID=deepseek-v4-flash \
uvicorn app.main:app --reload
```
（也可写入 `backend/.env`。）
```

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml README.md
git commit -m "docs: declare openai dep and document DeepSeek provider setup"
```

---

### Task 7: 全量验证 + 手动冒烟

- [ ] **Step 1: 全量测试**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: 全部 PASS

- [ ] **Step 2: 离线冒烟**（fake 模式确认无回归）

Run: `NOVEL_KG_USE_FAKE_LLM=1 uvicorn app.main:app --reload`（或直接 `PYTHONPATH=. python -c "from app.pipeline import llm; ..."`）
Expected: 启动正常

- [ ] **Step 3: DeepSeek 真实冒烟**（需 key；`backend/.env` 配置 `NOVEL_KG_LLM_PROVIDER=openai_compatible` + api_key）

```python
from app.pipeline import llm
from app.pipeline.ask import answer_question
from pydantic import BaseModel

class T(BaseModel):
    answer: str

out = llm.structured_output(T, "用一句话介绍《红楼梦》", system_prompt="你是助手", what="smoke")
print("STRUCTURED:", out.answer)
print("ASK:", answer_question("红楼梦", {"nodes": [], "edges": []}, None, None, "贾宝玉是谁？"))
```
Expected: STRUCTURED 与 ASK 都返回真实 DeepSeek 文本（agentic Q&A 走 `make_agent` → `OpenAIModel` tool-calling；若工具循环报错，单独排查 strands `OpenAIModel` streaming + DeepSeek function calling 兼容性）。

- [ ] **Step 4: `graphify update .`**

Run: `graphify update .`
Expected: 图更新到新模块（`pipeline/llm.py` 成为新节点）

---

### 风险与备注
- **agentic Q&A（ask.py）在 DeepSeek 上**：strands `OpenAIModel` 用 streaming + `tool_calls`，DeepSeek 官方支持 OpenAI 格式 function calling，预期可用；若异常（见 Task 7 Step 3），问题在 strands 的 OpenAI tool 流格式而非本改动。
- **DeepSeek `json_object` 需 prompt 含 "json" 字样**：`llm.py` 的 `_openai_structured_output` 已追加 `\n只输出JSON…`，规避 DeepSeek 的 `"Prompt must contain the word 'json'"` 报错。
- **向后兼容**：默认 `bedrock` 不变，现有 `.env`/README 行为零变化；`LLM_PROVIDER` 未来接 Kimi/GLM/Qwen 只需改 base_url + model_id。
