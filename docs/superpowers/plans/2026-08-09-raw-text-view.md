# 查看小说原文 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在阅读页新增"原文"Tab，让用户可以按章节展开查看小说原文，并支持从"时间轴"Tab 跳转到对应章节的原文。

**Architecture:** 后端新增一个只读路由 `GET /works/{work_id}/chapters/{chapter_id}/text`，直接复用已存在的 `store.read_chapters()` 从 `chapters.json` 里按需返回单章原文（不新增任何持久化逻辑）。前端新增 `RawTextTab.jsx`，完全照搬 `ArcsTab.jsx` 的"右侧栏章节目录 + 主区手风琴按需加载 + 本地按索引缓存"模式，并参考 `AskTab.jsx` 的 seed/nonce 机制实现从时间轴跳转后自动展开+定位到指定章节。

**Tech Stack:** FastAPI + Pydantic（后端），React 18 + Vite（前端），pytest（后端测试），无前端自动化测试框架（手工验证）。

---

## 前置说明（供实施者阅读，非任务步骤）

本计划基于已提交的设计文档 `docs/superpowers/specs/2026-08-09-raw-text-view-design.md`（commit `9c5bd0e`）。所有涉及的现有文件当前内容已逐行核对，行号均准确：

- `backend/app/models.py`（206行）：`ChapterSummary` 类在第122-125行。
- `backend/app/routes.py`（241行）：第11行导入语句 `from .models import CreateWorkResponse, WorkStatus`；`get_timeline` 路由在第110-123行；`generate_chapter_summary` 路由从第126行开始。
- `backend/app/store.py`（215行）：`read_chapters(work_id) -> dict | None` 已存在（第64-69行），无需修改。
- `frontend/src/api.js`（84行）：`getTimeline(id)` 是最后一个导出函数，在第82-84行。
- `frontend/src/pages/ReaderPage.jsx`（139行）：`TABS` 数组在第14-23行；`const [askSeed, setAskSeed] = useState(null);` 在第30行；`askAbout` 函数在第47-50行；渲染区 `{tab === "story" && ...}` 在第119行，`{tab === "arcs" && ...}` 在第120行，`{tab === "timeline" && ...}` 在第121行。
- `frontend/src/components/tabs/TimelineTab.jsx`（110行，已含竖向布局+a11y修复）：函数签名在第4行；章节标题 `<div>` 在第78行。
- `frontend/src/components/tabs/ArcsTab.jsx`（124行）：手风琴+右栏目录参考模式。
- `frontend/src/components/tabs/AskTab.jsx`（105行）：seed/nonce 去重跳转参考模式（`lastHandledNonceRef`）。
- `backend/tests/test_routes.py`（78行）：`client` fixture 在第17-22行，`_seed_work_with_events` 辅助函数在第25-47行。

项目无前端自动化测试框架；后端测试须从 `backend/` 目录用 `PYTHONPATH=. pytest -q` 运行。本会话此前所有任务均直接在 `main` 分支上开发（用户已同意，无需 git worktree）。

---

### Task 1: 后端 — 新增章节原文模型 + 路由 + 测试

**Files:**
- Modify: `backend/app/models.py:122-125`（附近新增类）
- Modify: `backend/app/routes.py:11`（导入）与第110-126行之间（新增路由）
- Test: `backend/tests/test_routes.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_routes.py` 末尾新增以下三个测试（复用现有 `client` fixture，参照 `test_get_timeline_*` 系列的写法，无需依赖 `events.json`）：

```python
def test_get_chapter_text_returns_full_chapter(client):
    from app.models import WorkStatus

    work_id = "work-rawtext-ok"
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True, exist_ok=True)
    status = WorkStatus(work_id=work_id, title="测试作品", phase="done", progress=1.0)
    (wdir / "status.json").write_text(status.model_dump_json(), encoding="utf-8")
    (wdir / "chapters.json").write_text(
        json.dumps({"ch0001": {"title": "第一章", "text": "这是第一章的正文内容。"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    resp = client.get(f"/works/{work_id}/chapters/ch0001/text")

    assert resp.status_code == 200
    body = resp.json()
    assert body["chapter_id"] == "ch0001"
    assert body["title"] == "第一章"
    assert body["text"] == "这是第一章的正文内容。"


def test_get_chapter_text_404_when_chapters_missing(client):
    from app.models import WorkStatus

    work_id = "work-rawtext-no-chapters"
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True, exist_ok=True)
    status = WorkStatus(work_id=work_id, title="测试作品", phase="done", progress=1.0)
    (wdir / "status.json").write_text(status.model_dump_json(), encoding="utf-8")

    resp = client.get(f"/works/{work_id}/chapters/ch0001/text")

    assert resp.status_code == 404


def test_get_chapter_text_404_when_chapter_id_unknown(client):
    from app.models import WorkStatus

    work_id = "work-rawtext-unknown-chapter"
    wdir = config.work_dir(work_id)
    wdir.mkdir(parents=True, exist_ok=True)
    status = WorkStatus(work_id=work_id, title="测试作品", phase="done", progress=1.0)
    (wdir / "status.json").write_text(status.model_dump_json(), encoding="utf-8")
    (wdir / "chapters.json").write_text(
        json.dumps({"ch0001": {"title": "第一章", "text": "正文"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    resp = client.get(f"/works/{work_id}/chapters/ch9999/text")

    assert resp.status_code == 404
```

说明：`backend/tests/test_routes.py` 文件顶部已有 `import json` 和 `from app import config, store`（第8/13行），无需新增顶层导入；`WorkStatus` 沿用文件里 `_seed_work_with_events`（第25-47行）已有的局部导入写法 `from app.models import WorkStatus`，在每个测试函数内部单独 import（与现有代码风格一致），上面三个测试已按此写好，不需要改动导入块。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && PYTHONPATH=. pytest tests/test_routes.py -v -k chapter_text`
Expected: 3 个新测试均 FAIL（`404 Not Found`，因为路由尚不存在，FastAPI 对未注册路径默认返回404，但请确认失败原因是路由缺失而非其他 —— 若返回 200 说明测试写错了）。

- [ ] **Step 3: 实现**

在 `backend/app/models.py` 第122-125行（`ChapterSummary` 类）之后插入：

```python
class ChapterText(BaseModel):
    """Full persisted source text for one chapter (原文 tab)."""

    chapter_id: str
    title: str = ""
    text: str
```

在 `backend/app/routes.py`：

1. 将第11行 `from .models import CreateWorkResponse, WorkStatus` 改为：
```python
from .models import ChapterText, CreateWorkResponse, WorkStatus
```

2. 在 `get_timeline` 路由（第110-123行）结束之后、`generate_chapter_summary` 路由（第126行）开始之前，插入新路由：
```python
@router.get("/works/{work_id}/chapters/{chapter_id}/text", response_model=ChapterText)
async def get_chapter_text(work_id: str, chapter_id: str):
    """Return the persisted source text for one chapter (原文 tab)."""
    if store.get_status(work_id) is None:
        raise HTTPException(404, "作品不存在")
    chapters = store.read_chapters(work_id)
    if not chapters:
        raise HTTPException(404, "该作品未保存章节原文（请重新处理该作品以体验此功能）")
    chapter = chapters.get(chapter_id)
    if chapter is None:
        raise HTTPException(404, f"章节 {chapter_id} 不存在")
    return ChapterText(
        chapter_id=chapter_id,
        title=chapter.get("title") or chapter_id,
        text=chapter.get("text") or "",
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && PYTHONPATH=. pytest tests/test_routes.py -v -k chapter_text`
Expected: 3 个新测试全部 PASS。

再运行一次全量套件确认无回归：
Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: 通过数比修改前多3个，失败数与修改前完全一致（历史遗留的4个无关基线失败：`test_config_arc.py::test_arc_defaults`、`test_extract_arcs.py::test_extract_arcs_returns_registry_per_arc`、`test_llm.py::test_provider_defaults_to_bedrock`、`test_partition.py::test_partition_respects_arc_bounds`），无新增失败。

- [ ] **Step 5: 提交**

```bash
git add backend/app/models.py backend/app/routes.py backend/tests/test_routes.py
git commit -m "feat: add GET /works/{id}/chapters/{chapter_id}/text endpoint for raw chapter text"
```

---

### Task 2: 前端 — api.js 新增函数 + 新建 RawTextTab.jsx

**Files:**
- Modify: `frontend/src/api.js`（末尾新增函数）
- Create: `frontend/src/components/tabs/RawTextTab.jsx`

无自动化测试（项目前端无测试框架），本任务仅做静态构建检查（`npx vite build`），不写单元测试。

- [ ] **Step 1: 新增 api.js 函数**

在 `frontend/src/api.js` 第82-84行（`getTimeline` 函数）之后新增：

```js
export async function getChapterText(id, chapterId) {
  return json(await fetch(`${BASE}/works/${id}/chapters/${chapterId}/text`));
}
```

- [ ] **Step 2: 新建 RawTextTab.jsx**

创建 `frontend/src/components/tabs/RawTextTab.jsx`，完整内容：

```jsx
import { useEffect, useRef, useState } from "react";
import { getChapterText } from "../../api";

export default function RawTextTab({ id, ls, jump, setRight }) {
  const chapters = ls.chapters || [];
  const [openCh, setOpenCh] = useState(null);
  const [chState, setChState] = useState({});
  const chapterRefs = useRef({});
  const lastHandledNonceRef = useRef(null);

  async function loadChapter(i, chapter) {
    const existing = chState[i];
    if (existing && (existing.text || existing.loading)) {
      return;
    }
    setChState((s) => ({ ...s, [i]: { loading: true } }));
    try {
      const res = await getChapterText(id, chapter.chapter);
      setChState((s) => ({ ...s, [i]: { loading: false, text: res.text } }));
    } catch (e) {
      setChState((s) => ({ ...s, [i]: { loading: false, error: e.message } }));
    }
  }

  function toggleChapter(i, chapter) {
    if (openCh === i) {
      setOpenCh(null);
      return;
    }
    setOpenCh(i);
    loadChapter(i, chapter);
  }

  useEffect(() => {
    if (chapters.length === 0) {
      setRight(null);
      return () => setRight(null);
    }
    setRight(
      <div>
        <h3 className="font-serif text-sm font-semibold text-ink-900">章节目录</h3>
        <ul className="mt-3 space-y-1">
          {chapters.map((c, i) => (
            <li key={i}>
              <button
                type="button"
                onClick={() => toggleChapter(i, c)}
                className={`block w-full truncate rounded px-2 py-1 text-left text-sm ${
                  openCh === i
                    ? "border-l-2 border-seal-600 bg-seal-100/40 text-seal-600"
                    : "text-ink-900 hover:bg-paper-50"
                }`}
              >
                {c.title || c.chapter}
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
    return () => setRight(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapters, openCh]);

  useEffect(() => {
    if (!jump || jump.nonce === lastHandledNonceRef.current) return;
    const idx = chapters.findIndex((c) => c.chapter === jump.chapterId);
    if (idx === -1) return;
    lastHandledNonceRef.current = jump.nonce;
    setOpenCh(idx);
    loadChapter(idx, chapters[idx]);
    setTimeout(() => {
      chapterRefs.current[idx]?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jump, chapters]);

  if (chapters.length === 0) {
    return <div className="mx-auto max-w-3xl px-8 py-10 text-ink-600">暂无章节原文</div>;
  }

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <h2 className="font-serif text-lg font-semibold text-ink-900">原文</h2>
      <p className="mt-2 text-sm text-ink-600">点击章节展开原文</p>
      <div className="mt-4 divide-y divide-ink-300 rounded-card border border-ink-300 bg-white">
        {chapters.map((c, i) => {
          const open = openCh === i;
          const st = chState[i] || {};
          return (
            <div key={i} ref={(el) => (chapterRefs.current[i] = el)}>
              <button
                type="button"
                onClick={() => toggleChapter(i, c)}
                className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-ink-900"
              >
                <span>{c.title || c.chapter}</span>
                <span className={open ? "text-seal-600" : "text-ink-600"}>
                  {open ? "▾" : "▸"}
                </span>
              </button>
              {open && (
                <div className="whitespace-pre-wrap px-4 pb-4 text-sm leading-relaxed text-ink-900">
                  {st.loading && (
                    <span>
                      <span className="spinner" /> 加载中…
                    </span>
                  )}
                  {st.error && <span className="text-danger-600">{st.error}</span>}
                  {!st.loading && !st.error && (st.text || "（暂无原文）")}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: 静态检查与构建**

Run: `cd frontend && npx vite build`
Expected: 构建成功，无编译错误（可能有预存在的 chunk-size 警告，忽略）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/api.js frontend/src/components/tabs/RawTextTab.jsx
git commit -m "feat: add RawTextTab component and getChapterText API client"
```

---

### Task 3: 前端 — ReaderPage.jsx 接入原文 Tab 与跳转回调

**Files:**
- Modify: `frontend/src/pages/ReaderPage.jsx`

**依赖：Task 2 必须先完成**（本任务引用 `RawTextTab` 组件）。

- [ ] **Step 1: 新增 import**

在 `frontend/src/pages/ReaderPage.jsx` 现有的 `import ArcsTab ...` 语句之后新增：

```js
import RawTextTab from "../components/tabs/RawTextTab";
```

- [ ] **Step 2: TABS 数组新增"原文"**

将第14-23行的 `TABS` 数组，在 `{ key: "story", ... }` 之后、`{ key: "arcs", ... }` 之前插入一行：

```js
{ key: "raw", label: "原文" },
```

- [ ] **Step 3: 新增 rawJump state 与 viewChapter 回调**

紧跟第30行 `const [askSeed, setAskSeed] = useState(null);` 之后新增：

```js
const [rawJump, setRawJump] = useState(null);
```

紧跟第47-50行 `askAbout` 函数定义之后新增：

```js
function viewChapter(chapterId) {
  setRawJump({ chapterId, nonce: Date.now() });
  setTab("raw");
}
```

- [ ] **Step 4: 渲染区接入新 Tab 与传参**

在渲染区（第112-135行）里，`{tab === "story" && <StoryTab id={id} setRight={setRight} />}`（第119行）之后插入：

```jsx
{tab === "raw" && <RawTextTab id={id} ls={ls} jump={rawJump} setRight={setRight} />}
```

并将第121行的：

```jsx
{tab === "timeline" && <TimelineTab id={id} setRight={setRight} />}
```

改为：

```jsx
{tab === "timeline" && (
  <TimelineTab id={id} setRight={setRight} onViewChapter={viewChapter} />
)}
```

- [ ] **Step 5: 静态检查与构建**

Run: `cd frontend && npx vite build`
Expected: 构建成功，无编译错误。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/pages/ReaderPage.jsx
git commit -m "feat: wire up raw text tab and chapter jump in ReaderPage"
```

---

### Task 4: 前端 — TimelineTab.jsx 增加"查看原文"跳转按钮

**Files:**
- Modify: `frontend/src/components/tabs/TimelineTab.jsx`

**依赖：Task 3 必须先完成**（`onViewChapter` prop 由 `ReaderPage.jsx` 传入才能生效；本任务单独验证构建不受影响，但功能需 Task 3 落地才可实际点击验证）。

- [ ] **Step 1: 修改函数签名**

将 `frontend/src/components/tabs/TimelineTab.jsx` 第4行：

```jsx
export default function TimelineTab({ id, setRight }) {
```

改为：

```jsx
export default function TimelineTab({ id, setRight, onViewChapter }) {
```

- [ ] **Step 2: 章节标题行加跳转按钮**

将第78行：

```jsx
<div className="mb-2 text-xs font-semibold text-ink-600">{g.chapter_title}</div>
```

改为：

```jsx
<div className="mb-2 flex items-center justify-between gap-2">
  <span className="text-xs font-semibold text-ink-600">{g.chapter_title}</span>
  <button
    type="button"
    onClick={() => onViewChapter?.(g.chapter_id)}
    className="text-xs text-ink-600 hover:text-seal-600 hover:underline"
  >
    查看原文 →
  </button>
</div>
```

- [ ] **Step 3: 静态检查与构建**

Run: `cd frontend && npx vite build`
Expected: 构建成功，无编译错误。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/tabs/TimelineTab.jsx
git commit -m "feat: add jump-to-raw-text button on timeline chapter groups"
```

---

### Task 5: 全量验证

**Files:** 无代码改动，仅验证。

- [ ] **Step 1: 后端全量测试**

Run: `cd backend && PYTHONPATH=. pytest -q`
Expected: 相比 Task 1 之前的基线多3个通过，失败数仍为4个（同一批历史遗留无关失败：`test_config_arc.py::test_arc_defaults`、`test_extract_arcs.py::test_extract_arcs_returns_registry_per_arc`、`test_llm.py::test_provider_defaults_to_bedrock`、`test_partition.py::test_partition_respects_arc_bounds`），无新增失败。

- [ ] **Step 2: 前端构建**

Run: `cd frontend && npx vite build`
Expected: 构建成功。

- [ ] **Step 3: 手工验证清单**

需要 `npm run dev`（前端）+ 已运行的后端（含至少一个已处理完成的作品）配合，逐项确认：

1. 打开阅读页，确认顶部 Tab 顺序为：总览 / 人物 / 故事正片 / **原文** / 情节线 / 时间轴 / 图谱 / 问答 / 设置（"原文"在"故事正片"和"情节线"之间）。
2. 点击"原文"Tab，确认右侧栏出现完整章节目录列表。
3. 点击目录中任一章节（或主区任一章节手风琴条目），确认原文展开显示，且展开的是真实小说正文（非摘要）。
4. 收起该章节后再次展开，确认不重复发起网络请求（可用浏览器开发者工具 Network 面板确认第二次展开无新请求）。
5. 切到"时间轴"Tab，确认每个章节分组标题右侧出现"查看原文 →"按钮。
6. 点击该按钮，确认自动切换到"原文"Tab，对应章节自动展开并滚动到可见区域。
7. 再次点击同一个"查看原文 →"按钮（章节已展开的情况下），确认依然重新触发滚动定位（不是静默 no-op）。

- [ ] **Step 4: 检查 git 历史与工作树状态**

Run: `git log --oneline -8`
Expected: 依次看到 Task 1-4 的4个提交（`feat: add GET .../text endpoint...`、`feat: add RawTextTab component...`、`feat: wire up raw text tab...`、`feat: add jump-to-raw-text button...`），且顺序、提交信息前缀正确，无无关文件混入。

Run: `git status --short`
Expected: 无输出（工作树完全干净）。

（本任务无需 commit，仅验证。）
