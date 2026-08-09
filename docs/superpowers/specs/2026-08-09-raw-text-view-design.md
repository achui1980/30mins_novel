# 查看小说原文 — 设计文档

> 目标：新增一个"原文"Tab，让读者可以按章节查看小说的完整原文（而不仅是摘要/知识图谱），
> 并支持从"时间轴"Tab 的某个章节一键跳转到该章原文。

日期：2026-08-09
状态：设计已批准，待实施
关联文档：无（独立小功能）

---

## 1. 背景与现状

- 章节原文在解析阶段就已经完整持久化到 `data/works/{work_id}/chapters.json`
  （格式 `{chapter_id: {title, text}}`），由 `backend/app/pipeline/orchestrator.py:run_pipeline`
  写入，`backend/app/store.py:read_chapters(work_id)`（第 64-69 行）已提供读取函数，无需新增
  持久化逻辑。
- `backend/app/routes.py` 目前没有任何端点直接返回章节原文——最接近的
  `POST /works/{work_id}/chapters/{chapter_id}/summary`（第 126-151 行）只返回 LLM 摘要。
- `backend/app/models.py` 里 `LayeredSummary.chapters`（第 137-142 行）是
  `list[ChapterSummary]`（`chapter, title, summary` 三个字段），由
  `backend/app/pipeline/summarize.py` 生成时**包含全书所有章节**（`summary` 初始为空字符串，
  按需才生成），因此 `pkg.layered_summary.chapters` 已经是一份完整、可靠的章节目录数据源，
  `frontend/src/components/tabs/ArcsTab.jsx`（第 4-6 行）已经这样用来构建"章节摘要"手风琴的
  右侧目录。
- 前端 `frontend/src/pages/ReaderPage.jsx`（139 行）当前 8 个 Tab（第 14-23 行的 `TABS`
  数组），没有"原文"Tab。`ArcsTab.jsx` 提供了"右侧栏章节目录（`setRight`）+ 主区手风琴按需
  展开 + 本地按索引缓存"的现成交互模式，可直接复用于原文展示。
- `AskTab.jsx`（第 45-55 行）已有"外部触发跳转到某个 Tab 并自动执行一次操作"的现成模式：
  父级 `ReaderPage` 用 `{ question, nonce: Date.now() }` 传入一个"seed"对象，子组件用
  `lastHandledNonceRef` 只在 `nonce` 变化时触发一次，避免重复点击同一项被当作 no-op。本设计
  的"从时间轴跳转到原文对应章节"复用同一模式。
- 数据规模：实测单本小说约 30-60 万字、100+ 章（如《三国演义》109 章，全书 59.6 万字，
  平均每章约 5,475 字），因此原文必须按章节懒加载展示，不能一次性把全书渲染进 DOM。

## 2. 改动方案

只涉及后端一个新端点 + 前端一个新 Tab 组件 + 两处现有文件的小改动，不改变任何既有行为。

### 2.1 后端：新增 `ChapterText` 模型

`backend/app/models.py`，在 `ChapterSummary`（第 122-125 行）之后新增：

```python
class ChapterText(BaseModel):
    """Full persisted source text for one chapter (原文 tab)."""

    chapter_id: str
    title: str = ""
    text: str
```

### 2.2 后端：新增 `GET /works/{work_id}/chapters/{chapter_id}/text` 路由

`backend/app/routes.py`：

1. 第 11 行导入语句增加 `ChapterText`：
   ```python
   from .models import ChapterText, CreateWorkResponse, WorkStatus
   ```
2. 在 `get_timeline`（第 110-123 行）之后、`generate_chapter_summary`（第 126 行起）之前插入：
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
   404 检查顺序与 `generate_chapter_summary`（第 126-151 行）、`get_timeline`
   （第 110-123 行）等现有路由完全一致：先检作品是否存在，再检数据文件是否存在，最后检具体
   章节 id 是否存在。每次只返回单章（平均约 5,000 字），不会一次性把全书传给前端。

### 2.3 前端：`api.js` 新增 `getChapterText`

`frontend/src/api.js`，在 `getTimeline`（第 82-84 行）之后新增：

```js
export async function getChapterText(id, chapterId) {
  return json(await fetch(`${BASE}/works/${id}/chapters/${chapterId}/text`));
}
```

### 2.4 前端：新建 `RawTextTab.jsx`

新文件 `frontend/src/components/tabs/RawTextTab.jsx`，架构完全照搬
`ArcsTab.jsx`（第 4-30、32-61 行）的"章节目录（右栏）+ 手风琴按需加载 + 本地按索引缓存"模式，
额外增加一个 `jump` prop 用于支持从时间轴跳转（模式照搬 `AskTab.jsx` 第 45-55 行的
seed/nonce 去重触发机制）：

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

  // 跳转到指定章节（design §2.4：从时间轴"查看原文"点击而来）。`nonce` 每次点击都变化，
  // 因此重复点击同一章节也会再次触发跳转，而不是被当作 no-op（照搬 AskTab 的 seed/nonce 模式）。
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

要点：
- 右栏章节目录与主区手风琴逐字复用 `ArcsTab.jsx` 的现成写法（只是把 `getChapterSummary` 换
  成 `getChapterText`，把状态字段 `summary` 换成 `text`），保持项目内一致的交互与样式约定。
- 正文展示加 `whitespace-pre-wrap`（原文含大量换行，必须保留），字号/行高沿用项目里长文本
  的既有约定 `text-sm leading-relaxed text-ink-900`（与 `AskTab.jsx` 第 96 行一致）。
- 未展开的章节不会调用 `getChapterText`，也不会把原文字符串放进 DOM——同一时间最多只有一
  个手风琴条目处于展开+已加载状态，天然满足"不能一次性渲染全书"的约束。
- `chState` 按数组索引缓存已加载的原文，重复展开同一章节不会重复请求。

### 2.5 前端：`ReaderPage.jsx` 接入新 Tab + 跳转回调

`frontend/src/pages/ReaderPage.jsx`：

1. 新增 import：`import RawTextTab from "../components/tabs/RawTextTab";`
2. `TABS` 数组（第 14-23 行）在 `"story"` 之后、`"arcs"` 之前插入：
   ```js
   { key: "story", label: "故事正片" },
   { key: "raw", label: "原文" },
   { key: "arcs", label: "情节线" },
   ```
3. 新增状态（紧跟第 30 行 `askSeed` 之后）：
   ```js
   const [rawJump, setRawJump] = useState(null);
   ```
4. 新增回调（紧跟第 47-50 行 `askAbout` 之后，同样的 seed/nonce 写法）：
   ```js
   function viewChapter(chapterId) {
     setRawJump({ chapterId, nonce: Date.now() });
     setTab("raw");
   }
   ```
5. 渲染区（第 112-135 行）在 `{tab === "story" && ...}`（第 119 行）之后插入新分支，并给
   `TimelineTab` 传入 `onViewChapter`：
   ```jsx
   {tab === "story" && <StoryTab id={id} setRight={setRight} />}
   {tab === "raw" && <RawTextTab id={id} ls={ls} jump={rawJump} setRight={setRight} />}
   {tab === "arcs" && <ArcsTab id={id} ls={ls} setRight={setRight} />}
   {tab === "timeline" && (
     <TimelineTab id={id} setRight={setRight} onViewChapter={viewChapter} />
   )}
   ```

### 2.6 前端：`TimelineTab.jsx` 加"查看原文"按钮

`frontend/src/components/tabs/TimelineTab.jsx`：

1. 函数签名（第 4 行）增加 `onViewChapter` prop：
   ```jsx
   export default function TimelineTab({ id, setRight, onViewChapter }) {
   ```
2. 把第 78 行的章节标题：
   ```jsx
   <div className="mb-2 text-xs font-semibold text-ink-600">{g.chapter_title}</div>
   ```
   替换为标题+按钮的一行 flex 布局：
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
   按钮点击态样式沿用全项目一致的可点击文字规范 `hover:text-seal-600 hover:underline`
   （与 `CharactersTab.jsx` 的关系跳转按钮同款）。`onViewChapter?.()` 用可选调用防御
   `TimelineTab` 未来在其他地方被复用而不传该 prop 的情况。

## 3. 边界情况

- `chapters.json` 缺失（旧作品处理时该文件还未落盘的极端情况）：后端 `get_chapter_text`
  返回 404「该作品未保存章节原文……」，`RawTextTab` 的 `st.error` 分支展示该错误文案，只影响
  当前展开的这一条手风琴，不影响其他章节或整个 Tab。
- 请求的 `chapter_id` 不存在于 `chapters.json`：同样走 404，前端表现一致。
- 从时间轴跳转时 `chapters` 目录为空（`ls.chapters` 尚未就绪，理论上不会发生，因为进入
  `ReaderPage` 后 `pkg` 已加载完毕才能看到任何 Tab 内容）：`jump` 的 `useEffect` 里
  `chapters.findIndex(...) === -1` 时直接 return，不报错、不崩溃，只是这次跳转无效果。
- 跳转目标章节此前已经处于展开状态：`nonce` 每次点击都变化，效果等同于重新触发一次
  "展开+定位"，不会因为"已经是打开状态"而跳过滚动定位。
- 空文本/极短章节：`st.text || "（暂无原文）"` 兜底展示，不留空白区域。

## 4. 测试

后端（`backend/tests/test_routes.py`，遵循现有 `temp_data_root` fixture 写法）新增 3 个用例：

1. 正常返回单章原文（`{chapter_id, title, text}` 齐全）。
2. `chapters.json` 不存在 → 404。
3. `chapter_id` 不在 `chapters.json` 中 → 404。

前端无自动化测试框架，走静态检查 + 手工验证：

1. `npx vite build` 无编译错误。
2. `npm run dev` 打开任意已处理完成的作品，确认新增"原文"Tab 显示在"故事正片"和"情节线"
   之间。
3. 点击"原文"Tab，确认右侧栏出现章节目录，主区手风琴默认全部收起。
4. 点击任意章节，确认展开后显示该章原文（保留换行），再次点击收起后原文不丢失（本地缓存
   命中，不重复请求）。
5. 切到"时间轴"Tab，点击任意章节分组标题旁的"查看原文 →"，确认自动切换到"原文"Tab、
   对应章节自动展开并滚动到可见区域。
6. 重复点击同一章节的"查看原文 →"，确认每次都会重新滚动定位（而不是第二次点击无反应）。
</content>
