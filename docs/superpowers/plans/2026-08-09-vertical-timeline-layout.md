# 时间轴改为竖向排列 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把"时间轴"Tab（`frontend/src/components/tabs/TimelineTab.jsx`）从横向滚动布局改为竖向时间轴布局（左侧竖线+圆点，自上而下排列），交互逻辑完全不变。

**Architecture:** 仅修改 `TimelineTab.jsx` 一个文件的渲染部分（第 66-95 行），保留 `groups` 分组计算和 `selected`/`setSelected`/`setRight` 状态逻辑不变。用外层容器的 `border-l-2` 实现竖线，章节用大圆点、事件用小圆点+卡片，圆点颜色随 `isSelected` 与卡片高亮同步。

**Tech Stack:** React 18 + Vite + Tailwind CSS（无新增依赖）。

**关联设计文档：** `docs/superpowers/specs/2026-08-09-vertical-timeline-design.md`

---

### Task 1: 竖向时间轴渲染

**Files:**
- Modify: `frontend/src/components/tabs/TimelineTab.jsx:66-95`

当前第 66-95 行的完整内容（改动前）：

```jsx
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

- [ ] **Step 1: 替换为竖向时间轴渲染**

把上面这段完整替换为：

```jsx
  return (
    <div className="px-8 py-10">
      <p className="mb-4 text-sm text-ink-600">
        按章节顺序自上而下排列的关键情节事件，点击卡片查看详情。
      </p>
      <div className="relative border-l-2 border-ink-300 pl-6">
        {groups.map((g, gi) => (
          <div key={gi} className="relative mb-6">
            <span className="absolute -left-[29px] top-0.5 h-4 w-4 rounded-full border-[3px] border-paper-50 bg-pine-600" />
            <div className="mb-2 text-xs font-semibold text-ink-600">{g.chapter_title}</div>
            <div className="space-y-2">
              {g.events.map((e) => {
                const isSelected = selected?.seq === e.seq;
                return (
                  <div key={e.seq} className="relative">
                    <span
                      className={`absolute -left-[27px] top-3.5 h-2.5 w-2.5 rounded-full border-2 border-paper-50 ${
                        isSelected ? "bg-seal-600" : "bg-ink-300"
                      }`}
                    />
                    <button
                      type="button"
                      onClick={() => setSelected(isSelected ? null : e)}
                      className={`w-full rounded-card border p-3 text-left text-sm ${
                        isSelected
                          ? "border-seal-600 bg-seal-100/30 text-ink-900"
                          : "border-ink-300 bg-white text-ink-900"
                      }`}
                    >
                      {e.summary}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

要点（与设计文档 §2.2 一致）：
- 竖线由外层容器的 `border-l-2 border-ink-300` 实现，配合 `pl-6` 内边距。
- 章节大圆点 `bg-pine-600`（18px，3px 边框），事件小圆点默认 `bg-ink-300`（10px，2px 边框），选中时变为 `bg-seal-600`，与卡片高亮态同步。
- `isSelected` 变量在 `.map` 内提前提取，圆点和按钮共用，避免重复判断 `selected?.seq === e.seq`。
- `groups` 的计算逻辑（第 56-64 行）、`selected`/`setSelected`/`setRight` 状态与 `useEffect`（第 9-33 行）均不改动。
- 不再需要 `overflow-x-auto`（已移除），依赖 `AppShell.jsx` 中 `<main>` 已有的 `overflow-y-auto` 处理纵向滚动。

- [ ] **Step 2: 静态检查确认无遗漏的旧代码**

```bash
grep -n "overflow-x-auto\|横向滚动" frontend/src/components/tabs/TimelineTab.jsx
```

Expected: 无任何输出（说明横向滚动相关的类名和文案已全部替换）。

- [ ] **Step 3: 构建验证**

```bash
cd frontend && npx vite build
```

Expected: 构建成功（`✓ built in ...`），无编译错误（预存在的 chunk-size 警告可忽略，与本次改动无关）。

- [ ] **Step 4: 手动交互验证**

前置条件：后端已在 `:8000` 运行（`NOVEL_KG_USE_FAKE_LLM=1` 或已有历史处理完成的作品均可），前端用 `npm run dev` 启动。

按设计文档 §4 逐项确认：
1. 打开某个已处理作品的"时间轴"Tab。
2. 确认整体呈竖向排列：左侧一条竖线，章节标题旁有大圆点，事件卡片自上而下堆叠，无横向滚动条。
3. 点击一个事件卡片，确认卡片变为高亮态（红色边框+浅红背景），对应圆点变为红色（`bg-seal-600`），右侧详情面板显示该事件信息；再次点击同一张卡片，确认取消选中、圆点变回默认灰色（`bg-ink-300`）。
4. 滚动页面，确认整页可以正常纵向滚动查看全部章节和事件。
5. 用一本事件较多、章节较多的作品测试，确认竖线、圆点在不同章节标题长度下对齐正常，无明显错位或重叠。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/tabs/TimelineTab.jsx
git commit -m "feat: switch timeline tab to vertical layout with connector line"
```

---

## 完成后验证清单

- [ ] `frontend/src/components/tabs/TimelineTab.jsx` 中 `groups` 分组计算（原第 56-64 行）与 `useEffect`/状态逻辑（原第 4-33 行）字节级未变。
- [ ] `npx vite build` 无报错。
- [ ] `git status --short` 干净，只有这一个提交，只改了一个文件。
- [ ] `git log --oneline -3` 显示新提交位于 `76f354a`（设计文档）之上。
