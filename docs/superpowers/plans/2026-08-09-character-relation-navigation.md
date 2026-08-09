# 人物关系列表可点击跳转 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在"人物"Tab 的关系列表中，把对方人物姓名变成可点击项，点击后右侧详情面板切换到该人物自己的详情。

**Architecture:** 仅修改 `frontend/src/components/tabs/CharactersTab.jsx` 一个文件。`relations` 数组在计算时保留已经算出的 `otherId` 字段，关系列表 `<li>` 里的姓名文字包一层 `<button>`，`onClick` 调用现有的 `setSelectedId(r.otherId)`；`selectedId` 变化会自动触发现有 `useEffect`（第 19-77 行）重新计算并 `setRight(...)`，完全复用现有渲染路径，不新增状态、组件或后端改动。

**Tech Stack:** React 18 + Vite 5（前端），Tailwind utility classes，无前端自动化测试框架（沿用现状，仅手动验证 + `vite build` 静态检查）。

**关联设计文档：** `docs/superpowers/specs/2026-08-09-character-relation-navigation-design.md`

---

### Task 1: 关系列表姓名支持点击跳转

**Files:**
- Modify: `frontend/src/components/tabs/CharactersTab.jsx:30-34`（保留 `otherId`）
- Modify: `frontend/src/components/tabs/CharactersTab.jsx:55-63`（姓名变为可点击按钮）

当前这两段的完整现状（供对照，`useEffect` 全文见第 19-77 行）：

```jsx
    const relations = edges.map((e) => {
      const otherId = e.source === selectedId ? e.target : e.source;
      const other = graph?.nodes?.find((n) => n.id === otherId);
      return { label: other?.label || otherId, category: e.category };
    });
```

```jsx
              {relations.map((r, i) => (
                <li
                  key={i}
                  className="border-l-2 pl-2 text-sm text-ink-900"
                  style={{ borderColor: categoryColor(r.category) }}
                >
                  → {r.label}（{r.category}）
                </li>
              ))}
```

这个项目没有前端自动化测试框架（`AGENTS.md` 未列出前端测试命令），因此本任务不走 TDD 红绿循环，而是：编辑代码 → 静态构建检查 → 手动浏览器验证 → 提交。两处改动互相依赖（按钮的 `onClick` 需要用到保留下来的 `otherId`），作为一个原子改动一起完成。

- [ ] **Step 1: 编辑 `relations` 计算，保留 `otherId`**

将 `frontend/src/components/tabs/CharactersTab.jsx` 第 30-34 行（`const relations = edges.map(...)`）替换为：

```jsx
    const relations = edges.map((e) => {
      const otherId = e.source === selectedId ? e.target : e.source;
      const other = graph?.nodes?.find((n) => n.id === otherId);
      return { label: other?.label || otherId, category: e.category, otherId };
    });
```

（唯一变化：返回对象多了一个 `otherId` 字段，`otherId` 变量本身在原代码里已经存在，不新增查找逻辑。）

- [ ] **Step 2: 编辑关系列表渲染，姓名变为可点击按钮**

将（Step 1 完成后行号会整体不变，仍是原第 55-63 行）关系列表的 `<li>` 渲染块：

```jsx
              {relations.map((r, i) => (
                <li
                  key={i}
                  className="border-l-2 pl-2 text-sm text-ink-900"
                  style={{ borderColor: categoryColor(r.category) }}
                >
                  → {r.label}（{r.category}）
                </li>
              ))}
```

替换为：

```jsx
              {relations.map((r, i) => (
                <li
                  key={i}
                  className="border-l-2 pl-2 text-sm text-ink-900"
                  style={{ borderColor: categoryColor(r.category) }}
                >
                  →{" "}
                  <button
                    type="button"
                    onClick={() => setSelectedId(r.otherId)}
                    className="text-ink-900 hover:text-seal-600 hover:underline"
                  >
                    {r.label}
                  </button>
                  （{r.category}）
                </li>
              ))}
```

- [ ] **Step 3: 静态构建检查**

Run: `cd frontend && npx vite build`
Expected: 构建成功，无报错（无自动化测试框架，这是唯一的自动化检查手段——确认 JSX/语法正确）。

- [ ] **Step 4: 手动浏览器验证**

Run: `cd frontend && npm run dev`（另开终端保持运行；确保后端 `uvicorn app.main:app --reload` 也已在 `backend/` 目录下运行，且已有至少一个处理完成的作品可供打开，否则先按 `README`/首页正常上传流程跑通一个作品）

打开浏览器访问 `http://localhost:5173`，进入任意已处理完成作品的阅读页，切到"人物"Tab，依次确认：

1. 点击左侧任意人物卡片，右侧关系列表中的人名显示为可点击样式（默认深灰 `text-ink-900`，鼠标悬停时变为主题色 `seal-600` 并出现下划线）。
2. 点击关系列表中的一个人名，右侧详情面板切换为该人物自己的信息（姓名、描述、该人物自己的关系列表、出场章节全部正确更新为对方的数据）。
3. 若该关系列表中存在不属于"主要人物"卡片网格的对方人物，点击后详情仍正常显示，左侧卡片网格中没有对应高亮项（这是预期行为，不是 bug，不需要额外处理）。
4. 从新详情的关系列表中点回原来那个人物，确认可以正常来回切换（无需"返回上一个"按钮，直接点关系列表里对方的名字即可切回）。

Expected: 以上 4 点全部符合预期，控制台（浏览器 DevTools）无新增报错/警告。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/tabs/CharactersTab.jsx
git commit -m "feat: make character relation names clickable to jump to their detail"
```

---

## 完成后验证（无需新增任务，供实施者收尾核对）

- `git status --short` 应干净（除本次改动的一个文件已提交外，无其它遗留改动；若存在 `graphify-out/` 相关的脏文件，属于 AGENTS.md 中说明的正常现象，忽略即可）。
- `git show --stat HEAD` 应只显示 `frontend/src/components/tabs/CharactersTab.jsx` 一个文件、约 6 行改动（+4/-1 附近，具体以实际 diff 为准）。
- `git log --oneline -3` 应能看到本次提交排在设计文档提交 `092deee`（`docs: add design spec for character relation click navigation`）之后。
