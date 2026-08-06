# 前端 UI 重设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按照 `docs/superpowers/specs/2026-08-04-frontend-ui-redesign-design.md` 的设计，一次性重设 HomePage / ProcessingPage / ReaderPage（含 8 个 tab），引入 Tailwind CSS + lucide-react + 宣纸墨迹配色，并新增通用三栏应用壳（AppShell）。

**Architecture:** 新增 `frontend/src/components/AppShell.jsx` 作为三栏壳（左=书架切换器，中=各页面内容，右=按 tab 变化的上下文面板）。ReaderPage 从单个 651 行大文件拆分为 8 个独立 tab 组件（`frontend/src/components/tabs/*.jsx`），每个 tab 通过父组件传入的 `setRight(node)` 回调把自己的右栏内容"发布"给 AppShell（在 `useEffect` 里设置，卸载/切换时清空），避免 prop 层层下钻或 Context。HomePage/ProcessingPage 各自通过共享的 `useWorksList` hook 独立拉取作品列表（AppShell 也用同一个 hook 渲染左栏），接受轻微的重复请求以换取组件解耦。

**Tech Stack:** React 18 + Vite 5（既有）、新增 Tailwind CSS 3 + PostCSS + Autoprefixer、lucide-react 图标库、Google Fonts（Noto Sans SC / Noto Serif SC）。不改动后端、不改动 `api.js` 的接口签名。

**关于数据可用性的已知调整**（spec 是概念级设计，以下是对齐真实后端数据模型后的必要调整，均不影响功能，仅是文案/字段来源的具体化）：
- 人物详情面板的"引言"：后端 `MainCharacter`/图节点均无独立的 quote 字段，用节点的 `description` 字段以斜体呈现替代文学引言效果。
- 人物详情面板的"角色/人物关系"：`pkg.main_characters` 没有 `role` 字段，需要额外调用 `getGraph(id)` 找到对应节点取 `role`/`description`；"人物关系"从图的 `edges` 里筛选 source/target 命中该人物 id 的边；"出场章节"从 `getTimeline(id)` 的 `participants` 数组按人物 `label` 过滤后取 `chapter_title` 去重得到。
- HomePage 右栏统计：`WorkListItem` 没有创建时间字段，无法计算"本周新增"，右栏统计改为"作品总数 / 已完成 / 失败"三项。
- ProcessingPage 右栏：后端状态模型没有预计耗时字段，右栏改为"当前阶段说明文字 + 已完成阶段的简单日志列表"，不展示 ETA。

---

## 文件结构总览

**新增：**
- `frontend/tailwind.config.js`
- `frontend/postcss.config.js`
- `frontend/src/index.css`（替代 `styles.css`）
- `frontend/src/hooks/useWorksList.js`
- `frontend/src/components/AppShell.jsx`
- `frontend/src/components/SuggestedQuestions.jsx`
- `frontend/src/components/tabs/OverviewTab.jsx`
- `frontend/src/components/tabs/CharactersTab.jsx`
- `frontend/src/components/tabs/StoryTab.jsx`
- `frontend/src/components/tabs/ArcsTab.jsx`
- `frontend/src/components/tabs/TimelineTab.jsx`
- `frontend/src/components/tabs/GraphTab.jsx`
- `frontend/src/components/tabs/AskTab.jsx`
- `frontend/src/components/tabs/SettingsTab.jsx`

**修改：** `frontend/package.json`、`frontend/index.html`、`frontend/src/main.jsx`、`frontend/src/constants.js`、`frontend/src/pages/HomePage.jsx`、`frontend/src/pages/ProcessingPage.jsx`、`frontend/src/pages/ReaderPage.jsx`（重写为薄编排层）

**删除：** `frontend/src/styles.css`（Task 17，确认无引用后删除）

---

### Task 1: Tailwind / PostCSS / lucide-react / 字体安装配置

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/postcss.config.js`
- Create: `frontend/src/index.css`
- Modify: `frontend/src/main.jsx`
- Modify: `frontend/index.html`

- [ ] **Step 1: 安装依赖**

Run: `cd frontend && npm install -D tailwindcss@^3 postcss autoprefixer && npm install lucide-react`

Expected: `package.json` 的 `devDependencies` 新增 `tailwindcss`/`postcss`/`autoprefixer`，`dependencies` 新增 `lucide-react`。

- [ ] **Step 2: 创建 `tailwind.config.js`**

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        paper: { 50: "#FAF6EE", 100: "#F3ECDD" },
        ink: { 900: "#2B2724", 600: "#6B6259", 300: "#D9D2C4" },
        seal: { 100: "#F5DEDA", 600: "#B33A3A", 700: "#8F2C2C" },
        pine: { 100: "#DCE6E1", 600: "#3F5B4E" },
        amber: { 600: "#C9A15B" },
        danger: { 600: "#C0392B" },
      },
      fontFamily: {
        sans: ['"Noto Sans SC"', "Inter", "system-ui", "sans-serif"],
        serif: ['"Noto Serif SC"', "Georgia", "serif"],
      },
      borderRadius: { card: "12px", btn: "8px" },
      boxShadow: {
        sm2: "0 1px 2px rgba(43,39,36,.04)",
        pop: "0 8px 24px rgba(43,39,36,.08)",
      },
    },
  },
  plugins: [],
};
```

- [ ] **Step 3: 创建 `postcss.config.js`**

```js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 4: 创建 `frontend/src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #root {
  height: 100%;
}
* {
  box-sizing: border-box;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
.spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 2px solid #D9D2C4;
  border-top-color: #B33A3A;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
```

- [ ] **Step 5: 修改 `frontend/src/main.jsx` 的样式引入**

在 `main.jsx` 里找到 `import "./styles.css";`，替换为：

```js
import "./index.css";
```

- [ ] **Step 6: 在 `frontend/index.html` 的 `<head>` 里追加字体链接**

在现有 `<title>` 标签之后追加：

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link
  href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;600;700&family=Noto+Serif+SC:wght@500;600;700&display=swap"
  rel="stylesheet"
/>
```

- [ ] **Step 7: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功，无 Tailwind/PostCSS 报错（此时页面还是旧 JSX + 新 CSS，视觉上不会变化，只验证构建链路）。

- [ ] **Step 8: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/tailwind.config.js frontend/postcss.config.js frontend/src/index.css frontend/src/main.jsx frontend/index.html
git commit -m "chore(frontend): add tailwindcss/postcss/lucide-react tooling"
```

---

### Task 2: 更新 `constants.js` 配色（语义映射不变，仅换色值）

**Files:**
- Modify: `frontend/src/constants.js`

- [ ] **Step 1: 替换 `CATEGORY_COLORS` 的 8 个色值**

把 `frontend/src/constants.js` 里的：

```js
export const CATEGORY_COLORS = { 家人: "#e6550d", 爱人: "#e7298a", 朋友: "#2ca02c", 敌人: "#d62728", 师徒: "#1f77b4", 主仆: "#9467bd", 同盟: "#17becf", 其他: "#8c8c8c" };
```

替换为（在宣纸墨迹配色体系内选取的 8 个互相可区分的色相，键名/顺序不变）：

```js
export const CATEGORY_COLORS = {
  家人: "#3F5B4E",
  爱人: "#B33A3A",
  朋友: "#C9A15B",
  敌人: "#6B2E2E",
  师徒: "#4A6FA5",
  主仆: "#7B6D8D",
  同盟: "#3F7A6B",
  其他: "#8C8478",
};
```

其余内容（`CATEGORY_ORDER`、`categoryColor`、`PHASE_LABELS`、`PHASE_ORDER`）保持不变。

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/constants.js
git commit -m "style(frontend): update CATEGORY_COLORS to new palette"
```

---

### Task 3: `useWorksList` hook

**Files:**
- Create: `frontend/src/hooks/useWorksList.js`

- [ ] **Step 1: 创建 hook**

```js
import { useCallback, useEffect, useState } from "react";
import { listWorks } from "../api";

export function useWorksList() {
  const [works, setWorks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(() => {
    setLoading(true);
    listWorks()
      .then((data) => {
        setWorks(data);
        setError("");
      })
      .catch((e) => setError(e.message || "加载失败"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { works, loading, error, refresh };
}
```

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功（此文件暂无引用方，不影响页面渲染）。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useWorksList.js
git commit -m "feat(frontend): add useWorksList hook"
```

---

### Task 4: `AppShell` 三栏应用壳组件

**Files:**
- Create: `frontend/src/components/AppShell.jsx`

- [ ] **Step 1: 创建组件**

```jsx
import { Link, useNavigate } from "react-router-dom";
import { Plus, BookMarked, Trash2 } from "lucide-react";
import { useWorksList } from "../hooks/useWorksList";
import { deleteWork } from "../api";

export default function AppShell({ activeWorkId, right, children }) {
  const { works, loading, refresh } = useWorksList();
  const navigate = useNavigate();

  function openWork(w) {
    navigate(w.phase === "done" ? `/works/${w.work_id}` : `/works/${w.work_id}/processing`);
  }

  function removeWork(w, e) {
    e.stopPropagation();
    if (!window.confirm("确定删除这本书及其所有产出？")) return;
    deleteWork(w.work_id).then(refresh);
  }

  return (
    <div className="flex h-screen bg-paper-50 text-ink-900 font-sans text-sm">
      <aside className="flex w-[140px] shrink-0 flex-col overflow-y-auto border-r border-ink-300 bg-paper-100">
        <Link
          to="/"
          className="flex items-center gap-1.5 px-3 py-4 font-serif text-[15px] font-semibold text-ink-900 hover:text-seal-600"
        >
          <BookMarked size={16} strokeWidth={1.5} />
          <span>书架</span>
        </Link>
        <nav className="flex-1 space-y-0.5 px-1.5">
          {loading && <div className="px-2 py-1 text-xs text-ink-600">加载中…</div>}
          {!loading && works.length === 0 && (
            <div className="px-2 py-1 text-xs text-ink-600">暂无作品</div>
          )}
          {works.map((w) => {
            const active = w.work_id === activeWorkId;
            const bar =
              w.phase === "failed" ? "border-danger-600" : active ? "border-seal-600" : "border-pine-600";
            return (
              <button
                key={w.work_id}
                onClick={() => openWork(w)}
                title={w.title || w.work_id}
                className={`group flex w-full items-center gap-1 rounded-r border-l-[3px] ${bar} py-1.5 pl-2 pr-1 text-left text-xs hover:bg-paper-50 ${
                  active ? "bg-paper-50 font-medium" : ""
                }`}
              >
                <span className="flex-1 truncate">{w.title || w.work_id}</span>
                <Trash2
                  size={12}
                  strokeWidth={1.5}
                  className="shrink-0 text-ink-600 opacity-0 hover:text-danger-600 group-hover:opacity-100"
                  onClick={(e) => removeWork(w, e)}
                />
              </button>
            );
          })}
        </nav>
        <Link
          to="/"
          className="flex items-center gap-1 border-t border-ink-300 px-3 py-3 text-xs text-ink-600 hover:text-seal-600"
        >
          <Plus size={14} strokeWidth={1.5} />
          <span>新建</span>
        </Link>
      </aside>
      <main className="flex-1 overflow-y-auto">{children}</main>
      {right != null && (
        <aside className="w-[200px] shrink-0 overflow-y-auto border-l border-ink-300 bg-paper-100 p-3">
          {right}
        </aside>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功（AppShell 暂无页面引用，不影响现有页面渲染）。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AppShell.jsx
git commit -m "feat(frontend): add AppShell three-column layout"
```

---

### Task 5: 重写 `HomePage.jsx`

**Files:**
- Modify: `frontend/src/pages/HomePage.jsx`

- [ ] **Step 1: 用 AppShell 重写整个文件**

用以下内容整体替换 `frontend/src/pages/HomePage.jsx`：

```jsx
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createWork } from "../api";
import AppShell from "../components/AppShell";
import { useWorksList } from "../hooks/useWorksList";

export default function HomePage() {
  const [granularity, setGranularity] = useState("quick");
  const [drag, setDrag] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef(null);
  const navigate = useNavigate();
  const { works } = useWorksList();

  function handleFile(file) {
    if (!file) return;
    const name = file.name.toLowerCase();
    if (!name.endsWith(".txt") && !name.endsWith(".epub")) {
      setError("只支持 .txt 与 .epub 文件");
      return;
    }
    setError("");
    setUploading(true);
    createWork(file, granularity)
      .then((res) => navigate(`/works/${res.work_id}/processing`))
      .catch((e) => {
        setError(e.message || "上传失败");
        setUploading(false);
      });
  }

  function onDrop(e) {
    e.preventDefault();
    setDrag(false);
    handleFile(e.dataTransfer.files?.[0]);
  }

  const total = works.length;
  const done = works.filter((w) => w.phase === "done").length;
  const failed = works.filter((w) => w.phase === "failed").length;

  const stats = (
    <div className="space-y-4">
      <h2 className="font-serif text-sm font-semibold text-ink-900">概览</h2>
      <dl className="space-y-2 text-xs">
        <div className="flex justify-between">
          <dt className="text-ink-600">作品总数</dt>
          <dd className="font-medium">{total}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-ink-600">已完成</dt>
          <dd className="font-medium text-pine-600">{done}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-ink-600">失败</dt>
          <dd className="font-medium text-danger-600">{failed}</dd>
        </div>
      </dl>
    </div>
  );

  return (
    <AppShell right={stats}>
      <div className="mx-auto max-w-2xl px-8 py-12">
        <h1 className="font-serif text-3xl font-semibold text-ink-900">30 分钟读懂一本书</h1>
        <p className="mt-2 text-ink-600">上传一部小说，自动生成人物关系图谱与分层摘要。</p>

        {error && (
          <div className="mt-4 rounded-card border border-danger-600/40 bg-danger-600/5 px-4 py-2 text-sm text-danger-600">
            {error}
          </div>
        )}

        <div className="mt-6 flex items-center gap-3 text-sm">
          <span className="text-ink-600">提取档位：</span>
          <div className="inline-flex rounded-full border border-ink-300 p-0.5">
            {[
              ["quick", "快速"],
              ["complete", "完整"],
            ].map(([key, label]) => (
              <button
                key={key}
                onClick={() => setGranularity(key)}
                className={`rounded-full px-3 py-1 text-xs ${
                  granularity === key ? "bg-seal-600 text-white" : "text-ink-600 hover:text-ink-900"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div
          className={`mt-6 flex flex-col items-center justify-center rounded-card border-2 border-dashed px-6 py-16 text-center transition-colors ${
            drag ? "border-seal-600 bg-seal-100/40" : "border-ink-300"
          }`}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          onClick={() => fileRef.current?.click()}
        >
          {uploading ? (
            <>
              <span className="spinner" />
              <p className="mt-3 text-sm text-ink-600">上传中…</p>
            </>
          ) : (
            <>
              <p className="text-sm text-ink-900">拖拽小说文件到此，或点击选择</p>
              <p className="mt-1 text-xs text-ink-600">.txt 与 .epub，最大 25MB</p>
            </>
          )}
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.epub"
            className="hidden"
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
        </div>
      </div>
    </AppShell>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功。

- [ ] **Step 3: 启动前后端手动验证**

Run backend: `cd backend && NOVEL_KG_USE_FAKE_LLM=1 uvicorn app.main:app --reload`
Run frontend: `cd frontend && npm run dev`
用 chrome-devtools 打开 `http://localhost:5173/`，确认：三栏壳出现、左栏能看到 `data/works/` 里已有的作品（点击能跳转）、右栏统计数字与实际作品数一致、拖拽区/档位切换视觉符合宣纸墨迹风格。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/HomePage.jsx
git commit -m "feat(frontend): rebuild HomePage with AppShell and new design tokens"
```

---

### Task 6: 重写 `ProcessingPage.jsx`

**Files:**
- Modify: `frontend/src/pages/ProcessingPage.jsx`

- [ ] **Step 1: 用 AppShell 重写整个文件**

用以下内容整体替换 `frontend/src/pages/ProcessingPage.jsx`：

```jsx
import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { getStatus } from "../api";
import { PHASE_LABELS, PHASE_ORDER } from "../constants";
import AppShell from "../components/AppShell";

const PHASE_EXPLAIN = {
  queued: "任务已提交，等待处理开始。",
  parsing: "正在解析文本文件，切分章节与段落。",
  extracting: "正在从文本中抽取人物、地点、事件与关系。",
  building: "正在基于抽取结果构建知识图谱。",
  summarizing: "正在生成分层摘要与人物卡片。",
  done: "处理完成。",
  failed: "处理过程中出现错误。",
};

export default function ProcessingPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const timer = useRef(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const s = await getStatus(id);
        if (cancelled) return;
        setStatus(s);
        setError("");
        if (s.phase === "done") {
          navigate(`/works/${id}`, { replace: true });
          return;
        }
        if (s.phase === "failed") return;
        timer.current = setTimeout(poll, 2000);
      } catch (e) {
        if (cancelled) return;
        setError(e.message || "网络错误");
        timer.current = setTimeout(poll, 3000);
      }
    }
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer.current);
    };
  }, [id, navigate]);

  const phase = status?.phase || "queued";
  const failed = phase === "failed";
  const currentIdx = PHASE_ORDER.indexOf(phase);
  let pct = currentIdx >= 0 ? (currentIdx / (PHASE_ORDER.length - 1)) * 100 : 0;
  if (phase === "extracting" && typeof status?.progress === "number") {
    const span = 100 / (PHASE_ORDER.length - 1);
    pct = (currentIdx / (PHASE_ORDER.length - 1)) * 100 + status.progress * span;
  }

  const right = (
    <div className="space-y-4 text-xs">
      <h2 className="font-serif text-sm font-semibold text-ink-900">当前阶段说明</h2>
      <p className="text-ink-600">{PHASE_EXPLAIN[phase]}</p>
      <div className="space-y-1 border-t border-ink-300 pt-2">
        <h3 className="font-medium text-ink-900">进度日志</h3>
        {PHASE_ORDER.filter((p) => p !== "queued").map((p, i) => (
          <div
            key={p}
            className={`flex items-center gap-1.5 ${i <= currentIdx ? "text-pine-600" : "text-ink-600"}`}
          >
            <span>{i < currentIdx ? "✓" : i === currentIdx ? "●" : "○"}</span>
            <span>{PHASE_LABELS[p]}</span>
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <AppShell activeWorkId={id} right={failed ? null : right}>
      <div className="mx-auto max-w-2xl px-8 py-12">
        <h1 className="font-serif text-2xl font-semibold text-ink-900">{status?.title || "处理中"}</h1>

        {failed ? (
          <div className="mt-6 rounded-card border border-ink-300 bg-white p-6">
            <div className="rounded-card border border-danger-600/40 bg-danger-600/5 px-4 py-2 text-sm text-danger-600">
              处理失败：{status?.error || status?.message || "未知错误"}
            </div>
            <Link
              to="/"
              className="mt-4 inline-block rounded-btn bg-seal-600 px-4 py-2 text-sm text-white hover:bg-seal-700"
            >
              返回首页重试
            </Link>
          </div>
        ) : (
          <div className="mt-6 rounded-card border border-ink-300 bg-white p-6">
            <div className="flex items-center gap-2 text-sm text-ink-900">
              <span className="spinner" />
              <span>{PHASE_LABELS[phase]}</span>
              {status?.message && <span className="text-ink-600">· {status.message}</span>}
            </div>
            <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-ink-300">
              <div className="h-full bg-seal-600 transition-all" style={{ width: `${pct}%` }} />
            </div>
            <p className="mt-1 text-xs text-ink-600">{Math.round(pct)}%</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {PHASE_ORDER.filter((p) => p !== "queued").map((p, i) => (
                <span
                  key={p}
                  className={`rounded-full px-2.5 py-1 text-xs ${
                    i < currentIdx
                      ? "bg-pine-100 text-pine-600"
                      : i === currentIdx
                        ? "bg-seal-100 text-seal-600"
                        : "bg-paper-100 text-ink-600"
                  }`}
                >
                  {PHASE_LABELS[p]}
                </span>
              ))}
            </div>
            {error && <p className="mt-3 text-xs text-danger-600">网络错误，正在重试：{error}</p>}
            {status?.warnings?.length > 0 && (
              <p className="mt-3 text-xs text-amber-600">存在 {status.warnings.length} 条警告</p>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/ProcessingPage.jsx
git commit -m "feat(frontend): rebuild ProcessingPage with AppShell and new design tokens"
```

### Task 7: SuggestedQuestions 共享组件

**Files:**
- Create: `frontend/src/components/SuggestedQuestions.jsx`

- [ ] **Step 1: 编写代码**

```jsx
export default function SuggestedQuestions({ questions, onAsk }) {
  if (!questions || questions.length === 0) return null;
  return (
    <div>
      <h3 className="font-serif text-sm font-semibold text-ink-900">你可能想问</h3>
      <div className="mt-3 space-y-2">
        {questions.map((q, i) => (
          <button
            key={i}
            type="button"
            onClick={() => onAsk(q.question)}
            className="block w-full rounded-btn border border-ink-300 bg-white px-3 py-2 text-left text-sm text-ink-900 hover:border-seal-600 hover:bg-seal-100/30"
          >
            <div>{q.question}</div>
            {q.rationale && <div className="mt-1 text-xs text-ink-600">{q.rationale}</div>}
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/SuggestedQuestions.jsx
git commit -m "feat(frontend): add SuggestedQuestions shared component"
```

### Task 8: OverviewTab（总览 tab）

**Files:**
- Create: `frontend/src/components/tabs/OverviewTab.jsx`

总览 tab 不再渲染人物卡（人物卡已拆分到新的 CharactersTab，见 Task 9）。右栏常驻显示推荐问题 + 快速提问框。

- [ ] **Step 1: 编写代码**

```jsx
import { useEffect, useState } from "react";
import SuggestedQuestions from "../SuggestedQuestions";

export default function OverviewTab({ pkg, ls, onAsk, setRight }) {
  const questions = pkg.suggested_questions || [];
  const [q, setQ] = useState("");

  useEffect(() => {
    setRight(
      <div>
        <SuggestedQuestions questions={questions} onAsk={onAsk} />
        <div className="mt-6">
          <h3 className="font-serif text-sm font-semibold text-ink-900">快速提问</h3>
          <form
            className="mt-2 flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (q.trim()) onAsk(q.trim());
              setQ("");
            }}
          >
            <input
              className="rounded-btn border border-ink-300 bg-white px-3 py-2 text-sm"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="输入问题…"
            />
            <button
              type="submit"
              className="rounded-btn bg-seal-600 px-3 py-2 text-sm text-white hover:bg-seal-700"
            >
              提问
            </button>
          </form>
        </div>
      </div>
    );
    return () => setRight(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questions, q]);

  const hasOverview = ls.one_liner || ls.story_hook || ls.overview;

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      {hasOverview ? (
        <div className="rounded-card border border-ink-300 bg-white p-6">
          {ls.one_liner && (
            <p className="font-serif text-xl font-semibold text-ink-900">{ls.one_liner}</p>
          )}
          {ls.story_hook && <p className="mt-3 text-ink-600">{ls.story_hook}</p>}
          {ls.overview && <p className="mt-3 leading-relaxed text-ink-900">{ls.overview}</p>}
        </div>
      ) : (
        <div className="text-ink-600">暂无总览内容。</div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/tabs/OverviewTab.jsx
git commit -m "feat(frontend): add OverviewTab"
```

### Task 9: CharactersTab（人物 tab，新增）

**Files:**
- Create: `frontend/src/components/tabs/CharactersTab.jsx`

中间列表数据来自 `pkg.main_characters`。右栏详情需要补充 `getGraph(id)`（获取 `role`/`description` 与关系边）与 `getTimeline(id)`（获取出场章节，按 `participants` 数组匹配人物 `label`）。"引言"字段不存在，使用 `description` 斜体呈现替代。

- [ ] **Step 1: 编写代码**

```jsx
import { useEffect, useState } from "react";
import { getGraph, getTimeline } from "../../api";
import { categoryColor } from "../../constants";

export default function CharactersTab({ id, pkg, setRight }) {
  const mains = pkg.main_characters || [];
  const [selectedId, setSelectedId] = useState(mains[0]?.id || null);
  const [graph, setGraph] = useState(null);
  const [events, setEvents] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getGraph(id).then(setGraph).catch((e) => setError(e.message));
    getTimeline(id)
      .then((r) => setEvents(r.events || []))
      .catch(() => setEvents([]));
  }, [id]);

  useEffect(() => {
    if (!selectedId) {
      setRight(<div className="text-sm text-ink-600">点击左侧人物卡查看详情</div>);
      return () => setRight(null);
    }
    const node = graph?.nodes?.find((n) => n.id === selectedId);
    const main = mains.find((m) => m.id === selectedId);
    const label = node?.label || main?.label || "";
    const edges = (graph?.edges || graph?.links || []).filter(
      (e) => e.source === selectedId || e.target === selectedId
    );
    const relations = edges.map((e) => {
      const otherId = e.source === selectedId ? e.target : e.source;
      const other = graph?.nodes?.find((n) => n.id === otherId);
      return { label: other?.label || otherId, category: e.category };
    });
    const chapters = (events || [])
      .filter((ev) => ev.participants?.includes(label))
      .reduce(
        (acc, ev) => (acc.includes(ev.chapter_title) ? acc : [...acc, ev.chapter_title]),
        []
      );

    setRight(
      <div>
        <h3 className="font-serif text-lg font-semibold text-ink-900">{label}</h3>
        {node?.role && <p className="text-sm text-ink-600">{node.role}</p>}
        {(node?.description || main?.description) && (
          <p className="mt-3 text-sm italic text-ink-900">
            {node?.description || main?.description}
          </p>
        )}
        {relations.length > 0 && (
          <div className="mt-5">
            <h4 className="text-xs font-semibold uppercase text-ink-600">人物关系</h4>
            <ul className="mt-2 space-y-1.5">
              {relations.map((r, i) => (
                <li
                  key={i}
                  className="border-l-2 pl-2 text-sm text-ink-900"
                  style={{ borderColor: categoryColor(r.category) }}
                >
                  → {r.label}（{r.category}）
                </li>
              ))}
            </ul>
          </div>
        )}
        {chapters.length > 0 && (
          <div className="mt-5">
            <h4 className="text-xs font-semibold uppercase text-ink-600">出场章节</h4>
            <p className="mt-2 text-sm text-ink-900">{chapters.join("、")}</p>
          </div>
        )}
      </div>
    );
    return () => setRight(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, graph, events]);

  if (error) {
    return <div className="mx-auto max-w-3xl px-8 py-10 text-danger-600">{error}</div>;
  }

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <h2 className="font-serif text-lg font-semibold text-ink-900">主要人物</h2>
      {mains.length === 0 ? (
        <div className="mt-4 text-ink-600">未识别到主要人物</div>
      ) : (
        <div className="mt-4 grid grid-cols-2 gap-4">
          {mains.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setSelectedId(c.id)}
              className={`rounded-card border border-l-4 border-ink-300 bg-white p-4 text-left ${
                selectedId === c.id ? "border-l-seal-600" : "border-l-pine-600"
              }`}
            >
              <div className="font-medium text-ink-900">{c.label}</div>
              {c.description && (
                <div className="mt-1 line-clamp-2 text-sm text-ink-600">{c.description}</div>
              )}
              <div className="mt-2 text-xs text-ink-600">提及 {c.mention_count} 次</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/tabs/CharactersTab.jsx
git commit -m "feat(frontend): add CharactersTab"
```

### Task 10: StoryTab（故事正片 tab）

**Files:**
- Create: `frontend/src/components/tabs/StoryTab.jsx`

逻辑与旧版 `StoryFeature` 保持一致（懒加载每个节拍的故事文本），仅改样式；无右栏内容。

- [ ] **Step 1: 编写代码**

```jsx
import { useEffect, useState } from "react";
import { getBeats, getBeatStory } from "../../api";

export default function StoryTab({ id, setRight }) {
  const [meta, setMeta] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);
  const [beatState, setBeatState] = useState({});

  useEffect(() => {
    setRight(null);
  }, [setRight]);

  useEffect(() => {
    getBeats(id).then(setMeta).catch((e) => setError(e.message));
  }, [id]);

  async function toggleBeat(index) {
    if (open === index) {
      setOpen(null);
      return;
    }
    setOpen(index);
    const existing = beatState[index];
    if (existing && (existing.story || existing.loading)) return;
    setBeatState((s) => ({ ...s, [index]: { loading: true } }));
    try {
      const res = await getBeatStory(id, index);
      setBeatState((s) => ({ ...s, [index]: { loading: false, story: res.story } }));
    } catch (e) {
      setBeatState((s) => ({ ...s, [index]: { loading: false, error: e.message } }));
    }
  }

  if (error) {
    return (
      <div className="mx-auto max-w-3xl px-8 py-10 text-ink-600">
        {error}
        <div className="mt-2 text-sm text-ink-600">
          （此功能仅对新处理的作品生效，旧作品请重新上传处理体验。）
        </div>
      </div>
    );
  }
  if (!meta) {
    return (
      <div className="mx-auto max-w-3xl px-8 py-10 text-ink-600">
        <span className="spinner" /> 加载中…
      </div>
    );
  }

  const beats = meta.beats || [];
  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="rounded-card border border-ink-300 bg-white p-6">
        {meta.main_thread && (
          <p className="font-serif text-lg font-semibold text-ink-900">主线：{meta.main_thread}</p>
        )}
        {meta.tone && <p className="mt-2 text-sm text-ink-600">讲述基调：{meta.tone}</p>}
        <p className="mt-2 text-sm text-ink-600">点击任意情节节拍，按需生成该段的故事讲述。</p>
      </div>

      {beats.length === 0 ? (
        <div className="mt-6 text-ink-600">未生成情节节拍</div>
      ) : (
        <div className="mt-6 divide-y divide-ink-300 rounded-card border border-ink-300 bg-white">
          {beats.map((b) => {
            const isOpen = open === b.index;
            const st = beatState[b.index] || {};
            return (
              <div key={b.index}>
                <button
                  type="button"
                  onClick={() => toggleBeat(b.index)}
                  className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-ink-900"
                >
                  <span>
                    {b.index + 1}. {b.title}
                  </span>
                  <span className={isOpen ? "text-seal-600" : "text-ink-600"}>
                    {isOpen ? "▾" : "▸"}
                  </span>
                </button>
                {isOpen && (
                  <div className="px-4 pb-4 text-sm leading-relaxed text-ink-900">
                    {st.loading && (
                      <span>
                        <span className="spinner" /> 生成中…
                      </span>
                    )}
                    {st.error && <span className="text-danger-600">{st.error}</span>}
                    {!st.loading && !st.error && (st.story || "（暂无内容）")}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/tabs/StoryTab.jsx
git commit -m "feat(frontend): add StoryTab"
```

### Task 11: ArcsTab（情节线 tab）

**Files:**
- Create: `frontend/src/components/tabs/ArcsTab.jsx`

右栏为全书章节目录导航（特例，不是"选中详情"模式）：点击目录项调用与手风琴条目相同的 `toggleChapter`，保证懒加载摘要逻辑一致。

- [ ] **Step 1: 编写代码**

```jsx
import { useEffect, useState } from "react";
import { getChapterSummary } from "../../api";

export default function ArcsTab({ id, ls, setRight }) {
  const arcs = ls.arcs || [];
  const chapters = ls.chapters || [];
  const [openCh, setOpenCh] = useState(null);
  const [chState, setChState] = useState({});

  async function toggleChapter(i, chapter) {
    if (openCh === i) {
      setOpenCh(null);
      return;
    }
    setOpenCh(i);
    const existing = chState[i];
    if (
      (chapter.summary && chapter.summary.trim()) ||
      (existing && (existing.summary || existing.loading))
    ) {
      return;
    }
    setChState((s) => ({ ...s, [i]: { loading: true } }));
    try {
      const res = await getChapterSummary(id, chapter.chapter);
      setChState((s) => ({ ...s, [i]: { loading: false, summary: res.summary } }));
    } catch (e) {
      setChState((s) => ({ ...s, [i]: { loading: false, error: e.message } }));
    }
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

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <h2 className="font-serif text-lg font-semibold text-ink-900">情节线</h2>
      {arcs.length === 0 ? (
        <div className="mt-4 text-ink-600">未识别到情节线</div>
      ) : (
        <div className="mt-4 space-y-4">
          {arcs.map((a, i) => (
            <div key={i} className="rounded-card border border-ink-300 bg-white p-4">
              <div className="font-serif font-semibold text-ink-900">{a.title}</div>
              <div className="mt-2 text-sm leading-relaxed text-ink-900">{a.summary}</div>
              {a.member_characters?.length > 0 && (
                <div className="mt-2 text-xs text-ink-600">
                  涉及人物：{a.member_characters.join("、")}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {chapters.length > 0 && (
        <>
          <h2 className="mt-8 font-serif text-lg font-semibold text-ink-900">章节摘要</h2>
          <p className="mt-2 text-sm text-ink-600">点击章节，按需生成该章摘要</p>
          <div className="mt-4 divide-y divide-ink-300 rounded-card border border-ink-300 bg-white">
            {chapters.map((c, i) => {
              const open = openCh === i;
              const st = chState[i] || {};
              const body = (c.summary && c.summary.trim()) || st.summary;
              return (
                <div key={i}>
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
                    <div className="px-4 pb-4 text-sm leading-relaxed text-ink-900">
                      {st.loading && (
                        <span>
                          <span className="spinner" /> 生成中…
                        </span>
                      )}
                      {st.error && <span className="text-danger-600">{st.error}</span>}
                      {!st.loading && !st.error && (body || "（暂无摘要）")}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/tabs/ArcsTab.jsx
git commit -m "feat(frontend): add ArcsTab with chapter TOC navigation"
```

### Task 12: TimelineTab（时间轴 tab）

**Files:**
- Create: `frontend/src/components/tabs/TimelineTab.jsx`

逻辑与旧版 `TimelineTab` 一致，唯一变化：选中事件详情从内联展示移动到右栏。

- [ ] **Step 1: 编写代码**

```jsx
import { useEffect, useState } from "react";
import { getTimeline } from "../../api";

export default function TimelineTab({ id, setRight }) {
  const [events, setEvents] = useState(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    getTimeline(id)
      .then((r) => setEvents(r.events || []))
      .catch((e) => setError(e.message));
  }, [id]);

  useEffect(() => {
    if (!selected) {
      setRight(<div className="text-sm text-ink-600">点击时间轴上的事件查看详情</div>);
      return () => setRight(null);
    }
    setRight(
      <div>
        <h3 className="font-serif text-sm font-semibold text-ink-900">
          {selected.chapter_title} · 第 {selected.seq + 1} 个事件
        </h3>
        <p className="mt-3 text-sm leading-relaxed text-ink-900">{selected.summary}</p>
        {selected.participants?.length > 0 && (
          <p className="mt-3 text-xs text-ink-600">参与者：{selected.participants.join("、")}</p>
        )}
      </div>
    );
    return () => setRight(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  if (error) {
    return (
      <div className="mx-auto max-w-3xl px-8 py-10 text-ink-600">
        {error}
        <div className="mt-2 text-sm text-ink-600">
          （此功能仅对新处理的作品生效，旧作品请重新上传处理体验。）
        </div>
      </div>
    );
  }
  if (!events) {
    return (
      <div className="mx-auto max-w-3xl px-8 py-10 text-ink-600">
        <span className="spinner" /> 加载中…
      </div>
    );
  }
  if (events.length === 0) {
    return <div className="mx-auto max-w-3xl px-8 py-10 text-ink-600">未生成任何情节事件</div>;
  }

  const groups = [];
  for (const e of events) {
    const last = groups[groups.length - 1];
    if (last && last.chapter_id === e.chapter_id) {
      last.events.push(e);
    } else {
      groups.push({ chapter_id: e.chapter_id, chapter_title: e.chapter_title, events: [e] });
    }
  }

  return (
    <div className="px-8 py-10">
      <p className="mb-4 text-sm text-ink-600">
        按章节顺序排列的关键情节事件，横向滚动查看，点击卡片展开详情。
      </p>
      <div className="flex gap-6 overflow-x-auto pb-4">
        {groups.map((g, gi) => (
          <div key={gi} className="flex-shrink-0">
            <div className="mb-2 text-xs font-semibold text-ink-600">{g.chapter_title}</div>
            <div className="flex gap-2">
              {g.events.map((e) => (
                <button
                  key={e.seq}
                  type="button"
                  onClick={() => setSelected(selected?.seq === e.seq ? null : e)}
                  className={`w-48 rounded-card border p-3 text-left text-sm ${
                    selected?.seq === e.seq
                      ? "border-seal-600 bg-seal-100/30 text-ink-900"
                      : "border-ink-300 bg-white text-ink-900"
                  }`}
                >
                  {e.summary}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/tabs/TimelineTab.jsx
git commit -m "feat(frontend): add TimelineTab with detail moved to right column"
```

### Task 13: GraphTab（图谱 tab）

**Files:**
- Create: `frontend/src/components/tabs/GraphTab.jsx`

vis-network 逻辑与旧版 `GraphTab` 完全一致，唯一变化：选中节点/边的详情从内联展示移动到右栏。

- [ ] **Step 1: 编写代码**

```jsx
import { useEffect, useMemo, useRef, useState } from "react";
import { Network } from "vis-network/standalone";
import { getGraph } from "../../api";
import { CATEGORY_ORDER, categoryColor } from "../../constants";

const PLACE_TOP_N = 15;

export default function GraphTab({ id, setRight }) {
  const containerRef = useRef(null);
  const [graph, setGraph] = useState(null);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [showAllPlaces, setShowAllPlaces] = useState(false);

  useEffect(() => {
    getGraph(id).then(setGraph).catch((e) => setError(e.message));
  }, [id]);

  const edges = useMemo(() => {
    if (!graph) return [];
    return graph.edges || graph.links || [];
  }, [graph]);

  const placeCount = useMemo(() => {
    if (!graph) return 0;
    return (graph.nodes || []).filter((n) => n.node_type === "place").length;
  }, [graph]);

  useEffect(() => {
    if (!graph || !containerRef.current) return;
    const rawNodes = graph.nodes || [];

    const degree = {};
    for (const e of edges) {
      degree[e.source] = (degree[e.source] || 0) + 1;
      degree[e.target] = (degree[e.target] || 0) + 1;
    }

    let visibleNodes = rawNodes;
    if (!showAllPlaces) {
      const characters = rawNodes.filter((n) => n.node_type !== "place");
      const places = rawNodes.filter((n) => n.node_type === "place");
      const topPlaces = [...places]
        .sort((a, b) => (degree[b.id] || 0) - (degree[a.id] || 0))
        .slice(0, PLACE_TOP_N);
      visibleNodes = [...characters, ...topPlaces];
    }
    const visibleIds = new Set(visibleNodes.map((n) => n.id));

    const nodes = visibleNodes.map((n) => ({
      id: n.id,
      label: n.label,
      shape: n.node_type === "place" ? "box" : "dot",
      size: 12 + Math.min(20, (n.mention_count || 1) * 2),
      color:
        n.node_type === "place" ? { background: "#d9d9d9", border: "#b0b0b0" } : undefined,
      _raw: n,
    }));
    const visEdges = edges
      .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
      .map((e, i) => ({
        id: `e${i}`,
        from: e.source,
        to: e.target,
        color: { color: categoryColor(e.category) },
        width: Math.max(1, Math.min(6, e.weight || 1)),
        arrows: e.directed ? "to" : undefined,
        _raw: e,
      }));

    const network = new Network(
      containerRef.current,
      { nodes, edges: visEdges },
      {
        nodes: { font: { size: 15, face: "PingFang SC, Microsoft YaHei, sans-serif" } },
        edges: { smooth: { type: "continuous" } },
        physics: { stabilization: { iterations: 150 }, barnesHut: { springLength: 130 } },
        interaction: { hover: true, tooltipDelay: 120 },
      }
    );

    network.on("click", (params) => {
      if (params.nodes.length > 0) {
        const n = nodes.find((x) => x.id === params.nodes[0]);
        setDetail({ type: "node", data: n?._raw });
      } else if (params.edges.length > 0) {
        const e = visEdges.find((x) => x.id === params.edges[0]);
        setDetail({ type: "edge", data: e?._raw });
      } else {
        setDetail(null);
      }
    });

    return () => network.destroy();
  }, [graph, edges, showAllPlaces]);

  useEffect(() => {
    if (!detail?.data) {
      setRight(<div className="text-sm text-ink-600">点击图谱中的节点或连线查看详情</div>);
      return () => setRight(null);
    }
    if (detail.type === "node") {
      setRight(
        <div>
          <h3 className="font-serif text-lg font-semibold text-ink-900">{detail.data.label}</h3>
          {detail.data.role && <p className="text-sm text-ink-600">{detail.data.role}</p>}
          {detail.data.description && (
            <p className="mt-3 text-sm text-ink-900">{detail.data.description}</p>
          )}
          <p className="mt-4 text-xs text-ink-600">
            {detail.data.node_type === "place" ? "地点" : "人物"} · 提及{" "}
            {detail.data.mention_count || 0} 次
          </p>
        </div>
      );
    } else {
      setRight(
        <div>
          <div className="flex items-center gap-2">
            <span
              className="inline-block h-3 w-3 rounded-sm"
              style={{ background: categoryColor(detail.data.category) }}
            />
            <strong className="text-ink-900">{detail.data.category}</strong>
            <span className="text-xs text-ink-600">· {detail.data.confidence_label}</span>
          </div>
          {detail.data.detail && <p className="mt-3 text-sm text-ink-900">{detail.data.detail}</p>}
          {detail.data.evidence && (
            <p className="mt-3 text-sm italic text-ink-600">「{detail.data.evidence}」</p>
          )}
        </div>
      );
    }
    return () => setRight(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail]);

  if (error) return <div className="px-8 py-10 text-danger-600">{error}</div>;
  if (!graph) {
    return (
      <div className="px-8 py-10 text-ink-600">
        <span className="spinner" /> 加载图谱…
      </div>
    );
  }

  return (
    <div className="px-8 py-10">
      <div className="flex flex-wrap gap-4">
        {CATEGORY_ORDER.map((cat) => (
          <span key={cat} className="flex items-center gap-1.5 text-xs text-ink-600">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ background: categoryColor(cat) }}
            />
            {cat}
          </span>
        ))}
      </div>

      {placeCount > PLACE_TOP_N && (
        <label className="mt-3 flex items-center gap-2 text-sm text-ink-600">
          <input
            type="checkbox"
            checked={showAllPlaces}
            onChange={(e) => setShowAllPlaces(e.target.checked)}
          />
          显示全部地点（共 {placeCount} 个，默认只显示连接最多的 {PLACE_TOP_N} 个）
        </label>
      )}

      <div
        id="graph"
        ref={containerRef}
        className="mt-4 h-[560px] rounded-card border border-ink-300 bg-white"
      />
    </div>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/tabs/GraphTab.jsx
git commit -m "feat(frontend): add GraphTab with detail moved to right column"
```

### Task 14: AskTab（问答 tab）

**Files:**
- Create: `frontend/src/components/tabs/AskTab.jsx`

逻辑与旧版 `AskFeature` 一致，保留跨 tab 跳转自动提交（`seed`/`nonce`）模式；右栏常驻显示与总览相同的推荐问题列表。

- [ ] **Step 1: 编写代码**

```jsx
import { useEffect, useRef, useState } from "react";
import { getAskHistory, askQuestion } from "../../api";
import SuggestedQuestions from "../SuggestedQuestions";

export default function AskTab({ id, seed, questions, onAsk, setRight }) {
  const [history, setHistory] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  // Tracks the most recently *handled* seed nonce so the seed effect below
  // only calls runAsk once per distinct click, even though it re-runs on
  // every render where `loaded` or `seed` changes.
  const lastHandledNonceRef = useRef(null);

  useEffect(() => {
    setRight(<SuggestedQuestions questions={questions} onAsk={onAsk} />);
    return () => setRight(null);
  }, [questions, onAsk, setRight]);

  useEffect(() => {
    getAskHistory(id)
      .then((r) => setHistory(r.history || []))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, [id]);

  async function runAsk(questionText) {
    const question = (questionText || "").trim();
    if (!question || loading) return;
    setLoading(true);
    setError("");
    try {
      const res = await askQuestion(id, question);
      const entry = { question, answer: res.answer, cited: res.cited || [] };
      setHistory((h) => [...h, entry]);
      setQ("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  // A "seed" question (design §4.2c: click a suggested question -> jump here
  // and auto-submit). `nonce` changes on every click so re-clicking the same
  // question re-submits it instead of being a no-op. Gated on `loaded` so
  // this can only fire after the mount-time history load above has settled.
  useEffect(() => {
    if (loaded && seed && seed.nonce !== lastHandledNonceRef.current) {
      lastHandledNonceRef.current = seed.nonce;
      runAsk(seed.question);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed, loaded]);

  async function submit(e) {
    e.preventDefault();
    await runAsk(q);
  }

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="rounded-card border border-ink-300 bg-white p-6">
        <p className="text-sm text-ink-600">
          基于这本书的知识图谱与情节信息回答你的问题（仅依据已分析内容，不会凭空编造）。
        </p>
        <form onSubmit={submit} className="mt-4 flex gap-2">
          <input
            className="flex-1 rounded-btn border border-ink-300 px-3 py-2 text-sm"
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="例如：主角和反派是什么关系？"
            disabled={loading}
          />
          <button
            type="submit"
            className="rounded-btn bg-seal-600 px-4 py-2 text-sm text-white hover:bg-seal-700 disabled:opacity-50"
            disabled={loading || !q.trim()}
          >
            {loading ? "思考中…" : "提问"}
          </button>
        </form>
        {error && <div className="mt-3 text-sm text-danger-600">{error}</div>}
      </div>

      {loaded && history.length === 0 && !loading && (
        <div className="mt-6 text-ink-600">还没有问答记录，试着问一个问题吧。</div>
      )}

      <div className="mt-6 space-y-4">
        {[...history].reverse().map((item, i) => (
          <div key={i} className="rounded-card border border-ink-300 bg-white p-4">
            <p className="font-medium text-ink-900">Q：{item.question}</p>
            <p className="mt-2 whitespace-pre-wrap text-sm text-ink-900">{item.answer}</p>
            {item.cited?.length > 0 && (
              <p className="mt-2 text-xs text-ink-600">涉及：{item.cited.join("、")}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/tabs/AskTab.jsx
git commit -m "feat(frontend): add AskTab with cross-tab seed autosubmit"
```

### Task 15: SettingsTab（设置 tab）

**Files:**
- Create: `frontend/src/components/tabs/SettingsTab.jsx`

逻辑与旧版 `Settings` 一致，仅改样式；无右栏内容。

- [ ] **Step 1: 编写代码**

```jsx
import { useEffect } from "react";

export default function SettingsTab({ cards, setRight }) {
  useEffect(() => {
    setRight(null);
  }, [setRight]);

  if (cards.length === 0) {
    return <div className="mx-auto max-w-3xl px-8 py-10 text-ink-600">暂无设定卡</div>;
  }
  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="grid grid-cols-2 gap-4">
        {cards.map((c, i) => (
          <div key={i} className="rounded-card border border-ink-300 bg-white p-4">
            <div className="font-medium text-ink-900">{c.title}</div>
            <div className="mt-2 text-sm text-ink-600">{c.content}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/tabs/SettingsTab.jsx
git commit -m "feat(frontend): add SettingsTab"
```

### Task 16: 重写 ReaderPage.jsx 为薄编排层

**Files:**
- Modify: `frontend/src/pages/ReaderPage.jsx` (完全重写)

- [ ] **Step 1: 重写 ReaderPage.jsx**

```jsx
import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getWork, graphHtmlUrl } from "../api";
import AppShell from "../components/AppShell";
import OverviewTab from "../components/tabs/OverviewTab";
import CharactersTab from "../components/tabs/CharactersTab";
import StoryTab from "../components/tabs/StoryTab";
import ArcsTab from "../components/tabs/ArcsTab";
import TimelineTab from "../components/tabs/TimelineTab";
import GraphTab from "../components/tabs/GraphTab";
import AskTab from "../components/tabs/AskTab";
import SettingsTab from "../components/tabs/SettingsTab";

const TABS = [
  { key: "overview", label: "总览" },
  { key: "characters", label: "人物" },
  { key: "story", label: "故事正片" },
  { key: "arcs", label: "情节线" },
  { key: "timeline", label: "时间轴" },
  { key: "graph", label: "图谱" },
  { key: "ask", label: "问答" },
  { key: "settings", label: "设置" },
];

export default function ReaderPage() {
  const { id } = useParams();
  const [pkg, setPkg] = useState(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("overview");
  const [askSeed, setAskSeed] = useState(null);
  const [right, setRight] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getWork(id)
      .then((data) => {
        if (!cancelled) setPkg(data);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  function askAbout(question) {
    setAskSeed({ question, nonce: Date.now() });
    setTab("ask");
  }

  if (error) {
    return (
      <AppShell activeWorkId={id} right={null}>
        <div className="mx-auto max-w-3xl px-8 py-10">
          <Link to="/" className="text-sm text-ink-600 hover:text-seal-600">
            ← 返回首页
          </Link>
          <div className="mt-4 rounded-card border border-danger-600 bg-danger-600/10 px-4 py-3 text-sm text-danger-600">
            加载失败：{error}
          </div>
        </div>
      </AppShell>
    );
  }

  if (!pkg) {
    return (
      <AppShell activeWorkId={id} right={null}>
        <div className="flex h-full items-center justify-center">
          <span className="spinner" />
        </div>
      </AppShell>
    );
  }

  const ls = pkg.layered_summary || {};
  const questions = pkg.suggested_questions || [];

  return (
    <AppShell activeWorkId={id} right={right}>
      <div className="mx-auto max-w-4xl px-8 py-8">
        <div className="flex items-start justify-between gap-4">
          <h1 className="font-serif text-2xl text-ink-900">{pkg.title}</h1>
          <a
            href={graphHtmlUrl(id)}
            target="_blank"
            rel="noreferrer"
            className="whitespace-nowrap rounded-btn border border-ink-300 px-3 py-1.5 text-sm text-ink-600 hover:border-seal-600 hover:text-seal-600"
          >
            完整图谱 ↗
          </a>
        </div>

        <div className="mt-6 flex gap-6 border-b border-ink-300">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={
                "border-b-2 px-1 pb-3 text-sm transition-colors " +
                (tab === t.key
                  ? "border-seal-600 font-serif text-seal-600"
                  : "border-transparent text-ink-600 hover:text-ink-900")
              }
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="mt-6">
          {tab === "overview" && (
            <OverviewTab pkg={pkg} ls={ls} onAsk={askAbout} setRight={setRight} />
          )}
          {tab === "characters" && (
            <CharactersTab id={id} pkg={pkg} setRight={setRight} />
          )}
          {tab === "story" && <StoryTab id={id} setRight={setRight} />}
          {tab === "arcs" && <ArcsTab id={id} ls={ls} setRight={setRight} />}
          {tab === "timeline" && <TimelineTab id={id} setRight={setRight} />}
          {tab === "graph" && <GraphTab id={id} setRight={setRight} />}
          {tab === "ask" && (
            <AskTab
              id={id}
              seed={askSeed}
              questions={questions}
              onAsk={askAbout}
              setRight={setRight}
            />
          )}
          {tab === "settings" && (
            <SettingsTab cards={pkg.setting_cards || []} setRight={setRight} />
          )}
        </div>
      </div>
    </AppShell>
  );
}
```

- [ ] **Step 2: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功，无警告。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/ReaderPage.jsx
git commit -m "feat(frontend): rewrite ReaderPage as thin orchestrator with 8 tabs"
```

### Task 17: 删除旧 styles.css

**Files:**
- Delete: `frontend/src/styles.css`

- [ ] **Step 1: 确认没有文件仍在引用 styles.css**

Run: `grep -rn "styles.css" frontend/src`
Expected: 无输出（`main.jsx` 已在 Task 1 改为引入 `./index.css`）。

- [ ] **Step 2: 删除文件**

```bash
rm frontend/src/styles.css
```

- [ ] **Step 3: 验证构建**

Run: `cd frontend && npm run build`
Expected: 构建成功。

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(frontend): remove legacy styles.css"
```

### Task 18: 最终构建与人工验收

**Files:**
- None (verification only)

- [ ] **Step 1: 生产构建检查**

Run: `cd frontend && npm run build`
Expected: 构建成功，无 TypeScript/ESLint 报错（本项目无类型检查/lint 配置，仅需构建通过）。

- [ ] **Step 2: 启动后端（离线模式）与前端开发服务器**

Run (in `backend/`, separate terminal):
```bash
NOVEL_KG_USE_FAKE_LLM=1 uvicorn app.main:app --reload
```
Run (in `frontend/`, separate terminal):
```bash
npm run dev
```

- [ ] **Step 3: 人工走查三页面 + 8 个 Tab**

使用 `data/works/` 中已有的真实作品数据（包含 `done` 与 `failed` 两种状态的作品），通过浏览器手动检查以下内容：

1. **首页**：左侧书架列表正确显示所有作品（失败=红色左边框，正常=绿色左边框）；右栏统计数字（总数/已完成/失败）与列表一致；拖拽/点击上传区域样式正确；分档切换（快速/完整）可用。
2. **处理页**：进度条与阶段徽标正确显示当前阶段；右栏阶段说明文字和进度日志随阶段推进更新；失败作品显示错误提示与"返回首页重试"按钮。
3. **阅读页 - 总览**：中间显示一句话总结/故事钩子/概览；右栏常驻"你可能想问"列表 + 快速提问框，点击问题应跳转到问答 Tab 并自动提交。
4. **阅读页 - 人物**：中间人物卡网格可点击切换选中态（左边框变红）；右栏正确显示所选人物的角色/简介/人物关系列表/出场章节列表；无选中时显示占位文案。
5. **阅读页 - 故事正片**：手风琴展开/收起正常，懒加载内容正确显示；旧作品显示"仅对新处理作品生效"提示；无右栏内容。
6. **阅读页 - 情节线**：中间情节线卡片与章节摘要手风琴正常；右栏章节目录导航可点击跳转/展开对应章节，当前展开章节高亮。
7. **阅读页 - 时间轴**：横向滚动轨道正常，点击事件卡片后右栏显示该事件详情（章节/顺序/摘要/参与者）；未选中时右栏显示占位文案。
8. **阅读页 - 图谱**：`vis-network` 图谱正常渲染，图例与地点显示切换正常；点击节点/边后右栏显示对应详情（人物：角色/简介；关系：类别/置信度/证据引文）。
9. **阅读页 - 问答**：提交问题与历史记录展示正常；从总览跳转过来的问题能自动提交一次（不重复触发）；右栏常驻推荐问题列表。
10. **阅读页 - 设置**：设定卡网格正常显示，无右栏内容。

- [ ] **Step 4: 记录并修复走查中发现的问题**

若发现样式错位、右栏未清空（切换 Tab 后残留上一个 Tab 的右栏内容）、请求报错等问题，直接在对应组件文件中修复，并重新执行 Step 1-3 验证，然后单独提交修复。

- [ ] **Step 5: 最终 Commit（若有走查修复）**

```bash
git add -A
git commit -m "fix(frontend): address issues found in manual walkthrough"
```

若走查全程无问题，无需额外提交，Task 18 视为完成。
