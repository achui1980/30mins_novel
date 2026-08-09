# .mobi 上传格式支持 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户可以上传 `.mobi` 格式小说，走通完整的解析→抽取→建图→摘要 pipeline，产出与 `.txt`/`.epub` 同等质量的结果。

**Architecture:** 新增 `parse_mobi()` 函数（`backend/app/pipeline/parse.py`），用 `mobi` 库把 MOBI 容器解包为 `.epub` 或 `.html`，再原样委托给已存在的 `parse_epub()`/`parse_txt()`。`parse_upload()` 分发器新增一个 `.mobi` 分支。不改动 `Chapter`/`ParsedNovel` 中间表示，不改动任何下游 pipeline 代码。

**Tech Stack:** Python 3.11+, `mobi` PyPI 库（GPL-3.0，纯 Python，无系统依赖）, 现有 `ebooklib` + `beautifulsoup4`, pytest + `monkeypatch`（mock 驱动，无二进制 fixture）, React 18 前端。

**关联文档：** `docs/superpowers/specs/2026-08-08-mobi-format-support-design.md`（本计划的设计依据）

---

### Task 1: 添加 `mobi` 依赖

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: 在依赖列表中新增 `mobi`**

在 `backend/pyproject.toml` 的 `dependencies` 数组中，`"beautifulsoup4>=4.12",` 一行之后新增一行：

```toml
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "python-multipart>=0.0.9",
    "pydantic>=2.6",
    "ebooklib>=0.18",
    "beautifulsoup4>=4.12",
    "mobi>=0.4",
    "graphifyy>=0.1",
    "strands-agents>=0.1",
    "openai>=1.40",
    "boto3>=1.34",
]
```

- [ ] **Step 2: 安装依赖到 venv**

Run: `cd backend && .venv/bin/pip install "mobi>=0.4"`

Expected: 安装成功，输出以 `Successfully installed mobi-...` 结尾（可能连带装 KindleUnpack 所需的少量依赖，如 `Pillow`）。

- [ ] **Step 3: 验证可导入**

Run: `cd backend && .venv/bin/python -c "import mobi; print(mobi.extract)"`

Expected: 打印出一个函数对象，如 `<function extract at 0x...>`，无报错。

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml
git commit -m "build: add mobi dependency for .mobi upload support"
```

---

### Task 2: 配置层放行 `.mobi` 扩展名

**Files:**
- Modify: `backend/app/config.py:54`
- Test: `backend/tests/test_config_arc.py`（新增一个独立测试函数，不改动已有函数）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_config_arc.py` 文件末尾新增：

```python
def test_mobi_extension_allowed():
    assert ".mobi" in config.ALLOWED_EXTENSIONS
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_config_arc.py::test_mobi_extension_allowed -v`

Expected: FAIL，`AssertionError: assert '.mobi' in {'.txt', '.epub'}`

- [ ] **Step 3: 修改 `ALLOWED_EXTENSIONS`**

`backend/app/config.py:54` 原为：

```python
ALLOWED_EXTENSIONS = {".txt", ".epub"}
```

改为：

```python
ALLOWED_EXTENSIONS = {".txt", ".epub", ".mobi"}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_config_arc.py -v`

Expected: 全部 PASS（包括原有的 `test_arc_defaults`、`test_strong_provider_inherits_llm_provider` 和新增的 `test_mobi_extension_allowed`）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_config_arc.py
git commit -m "feat: allow .mobi extension in upload whitelist"
```

---

### Task 3: `parse_mobi()` — HTML 产物分支

**Files:**
- Modify: `backend/app/pipeline/parse.py`
- Create: `backend/tests/test_parse.py`

这是解析层目前完全没有单测覆盖的第一个测试文件。本任务只实现 MOBI7/PalmDOC 格式（`mobi.extract()` 产出 `.html`）这一条路径。

- [ ] **Step 1: 创建 `test_parse.py` 并写第一个失败测试**

```python
"""Unit tests for backend/app/pipeline/parse.py's MOBI support.

mobi.extract() unpacks a .mobi container to a temp dir and returns a path to
the produced file, which is either .epub (KF8/mobi8), .html (older
MOBI7/PalmDOC), or .pdf (Kindle "Print Replica" -- not supported). We mock
mobi.extract() so no binary .mobi fixture is needed.
"""

import mobi
import pytest

from app.pipeline.parse import ParseError, parse_mobi


def test_parse_mobi_html_source(tmp_path, monkeypatch):
    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    html_file = extracted_dir / "book.html"
    html_file.write_text(
        "<html><body><h1>第一章</h1><p>正文内容一。</p></body></html>",
        encoding="utf-8",
    )

    def fake_extract(path):
        return str(extracted_dir), str(html_file)

    monkeypatch.setattr(mobi, "extract", fake_extract)

    novel = parse_mobi(tmp_path / "book.mobi", "测试书名")

    assert len(novel.chapters) == 1
    assert novel.chapters[0].title == "第一章"
    assert novel.chapters[0].text == "正文内容一。"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_parse.py::test_parse_mobi_html_source -v`

Expected: FAIL，`ImportError: cannot import name 'parse_mobi' from 'app.pipeline.parse'`

- [ ] **Step 3: 实现最小 `parse_mobi()`（仅 HTML 分支）**

在 `backend/app/pipeline/parse.py` 文件顶部的 import 区块（第 11-13 行）新增 `shutil`：

```python
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
```

在 `parse_epub()` 函数（第 106-143 行）之后、`parse_upload()` 函数（第 146 行）之前插入：

```python
def parse_mobi(path: Path, fallback_title: str) -> ParsedNovel:
    """Parse a MOBI file by unpacking it via the ``mobi`` library then
    delegating to parse_epub()/parse_txt() for the produced content."""
    try:
        import mobi  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ParseError(f"缺少 MOBI 解析依赖: {exc}") from exc

    tempdir, filepath = mobi.extract(str(path))
    try:
        inner_ext = Path(filepath).suffix.lower()
        if inner_ext in (".html", ".htm"):
            from bs4 import BeautifulSoup  # type: ignore

            html = Path(filepath).read_bytes()
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text("\n")
            return parse_txt(text, fallback_title)
        raise ParseError(f"不支持的 MOBI 内部格式: {inner_ext}")
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_parse.py::test_parse_mobi_html_source -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/parse.py backend/tests/test_parse.py
git commit -m "feat: parse_mobi() HTML (MOBI7) branch via mobi library"
```

---

### Task 4: `parse_mobi()` — EPUB 产物分支

**Files:**
- Modify: `backend/app/pipeline/parse.py`
- Modify: `backend/tests/test_parse.py`

新版 KF8/mobi8 格式的 `.mobi` 文件被 `mobi.extract()` 解包后产出的是 `.epub` 文件。本任务让 `parse_mobi()` 把这种情况委托给已有的 `parse_epub()`。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_parse.py` 文件末尾新增：

```python
def test_parse_mobi_epub_source(tmp_path, monkeypatch):
    from ebooklib import epub as epub_mod

    book = epub_mod.EpubBook()
    book.set_identifier("id123")
    book.set_title("测试电子书")
    book.set_language("zh")

    chapter = epub_mod.EpubHtml(title="第一章", file_name="chap_1.xhtml", lang="zh")
    chapter.content = "<h1>第一章</h1><p>正文内容一。</p>"
    book.add_item(chapter)
    book.toc = (chapter,)
    book.add_item(epub_mod.EpubNcx())
    book.add_item(epub_mod.EpubNav())
    book.spine = ["nav", chapter]

    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    epub_path = extracted_dir / "book.epub"
    epub_mod.write_epub(str(epub_path), book)

    def fake_extract(path):
        return str(extracted_dir), str(epub_path)

    monkeypatch.setattr(mobi, "extract", fake_extract)

    novel = parse_mobi(tmp_path / "book.mobi", "测试电子书")

    # parse_epub() also picks up the EPUB's own nav document as a spurious
    # extra "chapter" (pre-existing behavior, out of scope here) -- assert on
    # the real chapter by title instead of exact chapter count.
    real_chapter = next(c for c in novel.chapters if c.title == "第一章")
    assert "正文内容一" in real_chapter.text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_parse.py::test_parse_mobi_epub_source -v`

Expected: FAIL —— 走到 `raise ParseError(f"不支持的 MOBI 内部格式: {inner_ext}")`（`.epub` 尚未被处理），测试因捕获到未预期的 `ParseError` 而失败。

- [ ] **Step 3: 新增 EPUB 分支**

修改 `parse_mobi()`（Task 3 中新增的函数）里的分支判断，在 `if inner_ext in (".html", ".htm"):` 之前插入 `.epub` 分支：

```python
    tempdir, filepath = mobi.extract(str(path))
    try:
        inner_ext = Path(filepath).suffix.lower()
        if inner_ext == ".epub":
            return parse_epub(Path(filepath), fallback_title)
        if inner_ext in (".html", ".htm"):
            from bs4 import BeautifulSoup  # type: ignore

            html = Path(filepath).read_bytes()
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text("\n")
            return parse_txt(text, fallback_title)
        raise ParseError(f"不支持的 MOBI 内部格式: {inner_ext}")
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_parse.py -v`

Expected: 两个测试（`test_parse_mobi_html_source`、`test_parse_mobi_epub_source`）均 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/parse.py backend/tests/test_parse.py
git commit -m "feat: parse_mobi() EPUB (KF8/mobi8) branch via parse_epub()"
```

---

### Task 5: `parse_mobi()` — 不支持的内部格式（PDF / Print Replica）

**Files:**
- Modify: `backend/tests/test_parse.py`（`parse.py` 本任务无需改动，Task 3 已写好 `raise ParseError` 的 else 分支）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_parse.py` 文件末尾新增：

```python
def test_parse_mobi_unsupported_inner_format(tmp_path, monkeypatch):
    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    pdf_file = extracted_dir / "book.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 fake print-replica content")

    def fake_extract(path):
        return str(extracted_dir), str(pdf_file)

    monkeypatch.setattr(mobi, "extract", fake_extract)

    with pytest.raises(ParseError):
        parse_mobi(tmp_path / "book.mobi", "测试书名")

    # The temp dir mobi.extract() produced must be cleaned up even on error.
    assert not extracted_dir.exists()
```

- [ ] **Step 2: 运行测试确认结果**

Run: `cd backend && PYTHONPATH=. pytest tests/test_parse.py::test_parse_mobi_unsupported_inner_format -v`

Expected: PASS —— Task 3 里写的 `raise ParseError(f"不支持的 MOBI 内部格式: {inner_ext}")` 分支和 `finally: shutil.rmtree(...)` 已经覆盖了这个场景，此步骤是确认性质（无需改代码）。如果失败，说明 Task 3/4 的 `finally` 块写法有误，需回去检查缩进（`finally` 必须包裹住 if/elif/raise 三个分支，不能只包裹 return 语句）。

- [ ] **Step 3: 把错误信息改得更明确（可选的小优化）**

把 `parse.py` 里的：

```python
        raise ParseError(f"不支持的 MOBI 内部格式: {inner_ext}")
```

改为（更贴合设计文档 §2.2 的措辞，帮助用户理解为何 Print Replica 电子书不支持）：

```python
        raise ParseError(f"不支持的 MOBI 内部格式（可能是 Print Replica/PDF 电子书）: {inner_ext}")
```

- [ ] **Step 4: 重新运行测试确认仍通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_parse.py -v`

Expected: 三个测试全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/parse.py backend/tests/test_parse.py
git commit -m "test: cover unsupported MOBI inner format (PDF/Print Replica)"
```

---

### Task 6: `parse_mobi()` — `mobi.extract()` 本身抛异常（损坏/加密文件）

**Files:**
- Modify: `backend/app/pipeline/parse.py`
- Modify: `backend/tests/test_parse.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_parse.py` 文件末尾新增：

```python
def test_parse_mobi_extract_failure_raises_parse_error(tmp_path, monkeypatch):
    def fake_extract(path):
        raise RuntimeError("corrupted or DRM-protected mobi file")

    monkeypatch.setattr(mobi, "extract", fake_extract)

    with pytest.raises(ParseError):
        parse_mobi(tmp_path / "book.mobi", "测试书名")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_parse.py::test_parse_mobi_extract_failure_raises_parse_error -v`

Expected: FAIL —— 当前 `tempdir, filepath = mobi.extract(str(path))` 没有 try/except 包裹，`RuntimeError` 会直接向上抛出，pytest 报 `Failed: DID NOT RAISE <class 'app.pipeline.parse.ParseError'>` 或直接因未捕获异常而 ERROR。

- [ ] **Step 3: 包裹 `mobi.extract()` 调用**

把 `parse_mobi()` 里的：

```python
    tempdir, filepath = mobi.extract(str(path))
    try:
```

改为：

```python
    try:
        tempdir, filepath = mobi.extract(str(path))
    except Exception as exc:  # noqa: BLE001 - surface a clean error
        raise ParseError(f"MOBI 解析失败: {exc}") from exc

    try:
```

（即在原来的 `try:`/`finally:` 结构外面，再包一层新的 `try/except`，专门捕获 `mobi.extract()` 本身的失败；原有的内层 `try/finally` 结构不变，负责处理提取产物 + 清理临时目录。）

此时函数完整代码为：

```python
def parse_mobi(path: Path, fallback_title: str) -> ParsedNovel:
    """Parse a MOBI file by unpacking it via the ``mobi`` library then
    delegating to parse_epub()/parse_txt() for the produced content."""
    try:
        import mobi  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ParseError(f"缺少 MOBI 解析依赖: {exc}") from exc

    try:
        tempdir, filepath = mobi.extract(str(path))
    except Exception as exc:  # noqa: BLE001 - surface a clean error
        raise ParseError(f"MOBI 解析失败: {exc}") from exc

    try:
        inner_ext = Path(filepath).suffix.lower()
        if inner_ext == ".epub":
            return parse_epub(Path(filepath), fallback_title)
        if inner_ext in (".html", ".htm"):
            from bs4 import BeautifulSoup  # type: ignore

            html = Path(filepath).read_bytes()
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text("\n")
            return parse_txt(text, fallback_title)
        raise ParseError(f"不支持的 MOBI 内部格式（可能是 Print Replica/PDF 电子书）: {inner_ext}")
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_parse.py -v`

Expected: 全部 4 个测试 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/parse.py backend/tests/test_parse.py
git commit -m "fix: wrap mobi.extract() failures into ParseError"
```

---

### Task 7: 把 `.mobi` 接入 `parse_upload()` 分发器

**Files:**
- Modify: `backend/app/pipeline/parse.py:146-156`
- Modify: `backend/tests/test_parse.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_parse.py` 文件末尾新增：

```python
def test_parse_upload_dispatches_mobi_extension(tmp_path, monkeypatch):
    from app.pipeline.parse import parse_upload

    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    html_file = extracted_dir / "book.html"
    html_file.write_text(
        "<html><body><h1>第一章</h1><p>正文内容。</p></body></html>",
        encoding="utf-8",
    )

    def fake_extract(path):
        return str(extracted_dir), str(html_file)

    monkeypatch.setattr(mobi, "extract", fake_extract)

    mobi_path = tmp_path / "book.mobi"
    mobi_path.write_bytes(b"fake mobi container bytes")

    novel = parse_upload(mobi_path, "book.mobi")

    assert novel.chapters[0].title == "第一章"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_parse.py::test_parse_upload_dispatches_mobi_extension -v`

Expected: FAIL —— `ParseError: 不支持的文件类型: .mobi`（`parse_upload()` 还没有 `.mobi` 分支）。

- [ ] **Step 3: 新增分发分支**

`backend/app/pipeline/parse.py:146-156` 原为：

```python
def parse_upload(path: Path, original_filename: str) -> ParsedNovel:
    """Dispatch to the right parser based on file extension."""
    ext = Path(original_filename).suffix.lower()
    fallback_title = Path(original_filename).stem or "未命名作品"
    if ext == ".txt":
        raw = path.read_bytes()
        text = _decode_text(raw)
        return parse_txt(text, fallback_title)
    if ext == ".epub":
        return parse_epub(path, fallback_title)
    raise ParseError(f"不支持的文件类型: {ext}")
```

改为：

```python
def parse_upload(path: Path, original_filename: str) -> ParsedNovel:
    """Dispatch to the right parser based on file extension."""
    ext = Path(original_filename).suffix.lower()
    fallback_title = Path(original_filename).stem or "未命名作品"
    if ext == ".txt":
        raw = path.read_bytes()
        text = _decode_text(raw)
        return parse_txt(text, fallback_title)
    if ext == ".epub":
        return parse_epub(path, fallback_title)
    if ext == ".mobi":
        return parse_mobi(path, fallback_title)
    raise ParseError(f"不支持的文件类型: {ext}")
```

- [ ] **Step 4: 运行全部 parse 测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_parse.py -v`

Expected: 全部 5 个测试 PASS。

- [ ] **Step 5: 更新模块 docstring**

`backend/app/pipeline/parse.py` 第 1 行原为：

```python
"""Parsing layer: raw upload (.txt / .epub) -> ordered list of chapters.
```

改为：

```python
"""Parsing layer: raw upload (.txt / .epub / .mobi) -> ordered list of chapters.
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/parse.py backend/tests/test_parse.py
git commit -m "feat: dispatch .mobi uploads to parse_mobi() in parse_upload()"
```

---

### Task 8: 前端放行 `.mobi` 上传

**Files:**
- Modify: `frontend/src/pages/HomePage.jsx:19-20,115,121`

这是纯前端 UI 改动，不涉及后端测试；用手动跑一次 dev server 加实际上传做验证（本项目前端没有已建立的单测框架，跟随现状不新增）。

- [ ] **Step 1: 更新扩展名校验（第 19-20 行）**

原为：

```jsx
    if (!name.endsWith(".txt") && !name.endsWith(".epub")) {
      setError("只支持 .txt 与 .epub 文件");
      return;
    }
```

改为：

```jsx
    if (!name.endsWith(".txt") && !name.endsWith(".epub") && !name.endsWith(".mobi")) {
      setError("只支持 .txt、.epub 与 .mobi 文件");
      return;
    }
```

- [ ] **Step 2: 更新提示文案（第 115 行）**

原为：

```jsx
              <p className="mt-1 text-xs text-ink-600">.txt 与 .epub，最大 25MB</p>
```

改为：

```jsx
              <p className="mt-1 text-xs text-ink-600">.txt、.epub 与 .mobi，最大 25MB</p>
```

- [ ] **Step 3: 更新文件选择器 `accept` 属性（第 121 行）**

原为：

```jsx
            accept=".txt,.epub"
```

改为：

```jsx
            accept=".txt,.epub,.mobi"
```

- [ ] **Step 4: 手动验证**

Run（另开一个终端窗口）：
```bash
cd frontend && npm run dev
```
在浏览器打开 `http://localhost:5173`，确认：
1. 拖拽区文案显示为 `.txt、.epub 与 .mobi，最大 25MB`。
2. 点击拖拽区弹出的系统文件选择框里，`.mobi` 文件可见可选（未被过滤掉）。
3. 选择一个非法扩展名文件（如 `.pdf`）仍会被前端拦截，报错文案含 `.mobi`。

Expected: 三点均符合预期。此步骤只是人工确认，不需要写自动化断言。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/HomePage.jsx
git commit -m "feat: accept .mobi uploads in the frontend drag/drop zone"
```

---

### Task 9: 更新权威设计文档中的格式描述

**Files:**
- Modify: `docs/superpowers/specs/2026-07-27-novel-knowledge-graph-design.md`

AGENTS.md 要求代码改动后同步这份"authoritative design spec"，其中 4 处硬编码了 `.txt / .epub` 这个固定组合。

- [ ] **Step 1: 更新摘要（约第 3 行）**

找到：

```
> 目标：上传一本小说（.txt / .epub）...
```

改为：

```
> 目标：上传一本小说（.txt / .epub / .mobi）...
```

（省略号部分为原文其余内容，保持不变，只替换括号内的格式列表。）

- [ ] **Step 2: 更新 §2 pipeline 总览图（约第 29-30 行）**

找到：

```
上传 .txt/.epub
  → 解析(epub→文本, 按章节切分)
```

改为：

```
上传 .txt/.epub/.mobi
  → 解析(epub/mobi→文本, 按章节切分)
```

- [ ] **Step 3: 更新 §6 API 契约（约第 108-110 行）**

找到：

```
POST /works（multipart: file .txt|.epub, granularity=quick|complete 默认 quick）...
```

改为：

```
POST /works（multipart: file .txt|.epub|.mobi, granularity=quick|complete 默认 quick）...
```

- [ ] **Step 4: 更新 §8 错误处理（约第 140 行）**

找到：

```
上传校验扩展名/大小；epub 解析失败 → 明确报错。
```

改为：

```
上传校验扩展名/大小；epub/mobi 解析失败 → 明确报错。
```

- [ ] **Step 5: 校验替换准确性**

Run: `grep -n "\.txt / \.epub\|\.txt/\.epub\|\.txt|\.epub\|epub 解析失败" docs/superpowers/specs/2026-07-27-novel-knowledge-graph-design.md`

Expected: 无匹配结果（说明所有旧的 `.txt/.epub` 固定搭配描述都已被替换为包含 `.mobi` 的版本）。如果有残留匹配，回到对应行补充修改。

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-07-27-novel-knowledge-graph-design.md
git commit -m "docs: mention .mobi support in the authoritative design spec"
```

---

### Task 10: 全量验证

**Files:** 无改动，只运行验证命令。

- [ ] **Step 1: 运行完整后端测试套件**

Run: `cd backend && PYTHONPATH=. pytest -q`

Expected: 全部测试 PASS，无 ERROR/FAILED（包括本计划新增的 `test_parse.py` 5 个测试、`test_config_arc.py` 新增的 1 个测试，以及所有既有测试——本计划未改动任何既有测试的行为）。

- [ ] **Step 2: 单独确认新增测试文件**

Run: `cd backend && PYTHONPATH=. pytest tests/test_parse.py -v`

Expected: 5 个测试全部 PASS：
- `test_parse_mobi_html_source`
- `test_parse_mobi_epub_source`
- `test_parse_mobi_unsupported_inner_format`
- `test_parse_mobi_extract_failure_raises_parse_error`
- `test_parse_upload_dispatches_mobi_extension`

- [ ] **Step 3: 确认 git 历史干净**

Run: `git log --oneline -10`

Expected: 看到本计划 Task 1-9 对应的 8 个 commit（`build:`/`feat:`/`test:`/`fix:`/`docs:` 前缀），每个 commit 只改动其任务范围内声明的文件，没有夹带无关文件。

- [ ] **Step 4: 确认工作区无遗留未提交改动**

Run: `git status --short`

Expected: 只有本计划开始前就已存在的、与 `.mobi` 功能无关的既有未提交改动（如果有），不应出现属于本功能但漏提交的文件。
