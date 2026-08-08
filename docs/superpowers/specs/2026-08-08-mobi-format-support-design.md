# 支持 .mobi 上传格式 — 设计文档

> 目标：在现有 `.txt`/`.epub` 上传格式基础上，新增对 Kindle `.mobi` 格式的支持，
> 复用现有 `ParsedNovel`/`Chapter` 中间表示与解析逻辑，不影响下游任何阶段。

日期：2026-08-08
状态：设计已批准，待实施
关联文档：`2026-07-27-novel-knowledge-graph-design.md`（§1 摘要、§2 pipeline 总览、§6 API 契约、§8 错误处理）

---

## 1. 背景与目标

### 1.1 现状

`backend/app/pipeline/parse.py` 中 `parse_upload(path, original_filename)` 是格式解析的唯一分发点，
根据文件扩展名分派给 `parse_txt()`（含 `_decode_text()` 多编码解码 + 中英文章节标题正则切分）或
`parse_epub()`（`ebooklib` + `BeautifulSoup` 遍历 spine 文档）。两者都产出统一的中间表示：

```python
@dataclass
class Chapter:
    index: int
    title: str
    text: str

@dataclass
class ParsedNovel:
    title: str
    chapters: list[Chapter]
```

下游 `chunk_novel → extract → graph 构建 → summarize`（`orchestrator.py`）只依赖 `ParsedNovel`，
对具体来源格式无感知。当前不支持 `.mobi`，上传时会在 `routes.py` 的扩展名白名单校验处直接 400。

### 1.2 目标

- 上传 `.mobi` 文件可以走通完整 pipeline，产出与 `.txt`/`.epub` 同等质量的章节切分结果。
- 不修改 `chunk_novel` 之后的任何下游逻辑——新增格式对下游完全透明。
- 遵循项目现有约定：解析失败统一转为 `ParseError`，pipeline 本身永不因解析异常而崩溃
  （`orchestrator.py` 捕获 `ParseError` 写入 `status.json` phase=failed）。

### 1.3 非目标

- 不支持 Kindle `.azw`/`.azw3` 变体格式，仅 `.mobi` 扩展名。
- 不支持 MOBI 内含的 "Print Replica"（本质是 PDF 排版，非纯文本）电子书——遇到则报错，不做 OCR/降级处理。
- 不引入 Calibre CLI 或其他系统级依赖；不新增二进制测试 fixture 文件。

---

## 2. 技术方案

### 2.1 依赖选型

使用 PyPI 的 `mobi` 库（`github.com/iscc/mobi`，`kevinhendricks/KindleUnpack` 去 GUI 的 fork）：

```python
import mobi
tempdir, filepath = mobi.extract("mybook.mobi")
```

- 纯 Python 实现，无系统级依赖（不需要安装 Calibre）。
- `mobi.extract()` 把 MOBI 容器解包到临时目录，`filepath` 指向解包产物，可能是：
  - `.epub`（新版 KF8/mobi8 格式，本质是 epub 结构）
  - `.html`（旧版 MOBI7/PalmDOC 格式）
  - `.pdf`（"Print Replica" 类电子书，非纯文本，本设计不支持）
- 调用方负责清理 `tempdir`（`shutil.rmtree`）。
- **许可证注意**：`mobi` 库为 **GPL-3.0-only**（继承自 KindleUnpack）。项目当前 `pyproject.toml`
  未声明 `license` 字段；作为内部 demo 暂不受影响，但若未来考虑开源发布/商业分发需重新评估。
- 库对损坏/加密(DRM)文件的失败模式未见文档化的专用异常类型，需用宽泛的 `except Exception`
  统一捕获并转换为项目的 `ParseError`。

### 2.2 解析流程

复用现有 `parse_epub()`/`parse_txt()`，不新增章节切分逻辑：

```
.mobi → mobi.extract() → 临时目录
                          ├─ *.epub → 复用 parse_epub()
                          ├─ *.html/*.htm → BeautifulSoup 提取纯文本 → 复用 parse_txt()
                          └─ *.pdf（或其它） → ParseError（不支持的电子书类型）
```

`backend/app/pipeline/parse.py` 新增：

```python
import shutil  # 文件顶部新增

def parse_mobi(path: Path, fallback_title: str) -> ParsedNovel:
    try:
        import mobi  # type: ignore
    except ImportError as exc:
        raise ParseError(f"缺少 MOBI 解析依赖: {exc}") from exc

    try:
        tempdir, filepath = mobi.extract(str(path))
    except Exception as exc:  # noqa: BLE001
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

`parse_upload()` 分发新增一行：

```python
if ext == ".mobi":
    return parse_mobi(path, fallback_title)
```

要点：
- `try/finally` 确保临时目录始终被清理，即使内部解析抛异常。
- 所有 `mobi` 库异常（损坏文件、DRM 加密等）统一转换为 `ParseError`，与现有错误处理约定一致。
- `import mobi`/`import bs4` 放函数内部，与 `parse_epub` 现有风格保持一致（延迟加载）。

### 2.3 配置与依赖清单

- `backend/app/config.py:54`：`ALLOWED_EXTENSIONS = {".txt", ".epub", ".mobi"}`
- `backend/pyproject.toml`：新增依赖 `"mobi>=0.4"`

### 2.4 前端改动

`frontend/src/pages/HomePage.jsx`：
- 扩展名校验（原第 19 行逻辑）：增加 `.mobi` 到允许列表。
- 文件选择器 `accept` 属性（原第 121 行）：`accept=".txt,.epub,.mobi"`
- 用户可见文案（原第 20、115 行）：`.txt / .epub` → `.txt / .epub / .mobi`

无需改动上传状态机、拖拽逻辑、章节颗粒度切换等其余部分。

---

## 3. 错误处理

沿用项目现有约定：
- 上传阶段：`routes.py` 的扩展名白名单校验会因 `.mobi` 加入白名单而放行，文件大小限制不变（25MB）。
- 解析阶段：MOBI 解包失败、内部格式不支持（PDF/Print Replica）、缺少 `mobi` 依赖三种情况均转换为
  `ParseError`，被 `orchestrator.run_pipeline` 捕获并记录到 `status.json`（`phase=failed`），
  不会导致进程崩溃或未处理异常。
- 临时目录清理：无论解析成功或失败，`finally` 块保证 `mobi.extract()` 产生的临时目录被删除，
  不残留磁盘垃圾。

---

## 4. 测试策略

新建 `backend/tests/test_parse.py`（当前解析层完全没有单元测试覆盖），使用 `monkeypatch` 模拟
`mobi.extract()`，不引入真实二进制 `.mobi` fixture 文件：

1. **HTML 产物路径**：mock `mobi.extract` 返回一个临时目录 + 手工构造的 `.html` 文件
   （内含"第一章"等标题标记），断言 `parse_mobi()` 返回的 `ParsedNovel` 章节数/标题符合预期
   （验证走到了 `parse_txt` 分支）。
2. **EPUB 产物路径**：mock `mobi.extract` 返回一个 `.epub` 临时文件，断言 `parse_mobi()` 正确
   委托给 `parse_epub()`（可复用/参照现有 epub 测试数据构造方式）。
3. **不支持的产物类型**：mock `mobi.extract` 返回一个 `.pdf` 临时文件，断言抛出 `ParseError`。
4. **底层库异常**：mock `mobi.extract` 直接抛异常（模拟损坏/加密文件），断言：
   - 抛出 `ParseError`（而非原始异常向上传播）；
   - 临时目录清理逻辑被正确触发（不残留）。
5. （可选）`backend/app/config.py` 的 `ALLOWED_EXTENSIONS` 包含 `.mobi` 的简单断言。

不修改 `backend/tests/test_pipeline_integration.py`——它目前只覆盖 `.txt` 端到端场景，`.epub`
也没有对应集成测试，为保持一致性，本次不为 `.mobi` 单独添加集成测试。

---

## 5. 文档更新

`docs/superpowers/specs/2026-07-27-novel-knowledge-graph-design.md` 中以下位置需同步补充 `.mobi`：
- 摘要（约第 3 行）：支持格式列表。
- §2 pipeline 总览图（约第 29-30 行）：`上传 .txt/.epub` → `上传 .txt/.epub/.mobi`。
- §6 API 契约（约第 108-110 行）：`POST /works` 的 `file` 参数支持格式说明。
- §8 错误处理（约第 140 行）：扩展名校验描述需提及 `.mobi`。

---

## 6. 改动清单汇总

1. `backend/pyproject.toml` — 新增 `mobi` 依赖。
2. `backend/app/pipeline/parse.py` — 新增 `parse_mobi()`，`parse_upload()` 新增 `.mobi` 分支，
   文件顶部新增 `import shutil`。
3. `backend/app/config.py` — `ALLOWED_EXTENSIONS` 加入 `.mobi`。
4. `frontend/src/pages/HomePage.jsx` — 扩展名校验、`accept` 属性、用户可见文案三处更新。
5. `backend/tests/test_parse.py`（新文件）— mock 驱动的 `parse_mobi()` 单元测试。
6. `docs/superpowers/specs/2026-07-27-novel-knowledge-graph-design.md` — 摘要、§2、§6、§8 四处更新。
