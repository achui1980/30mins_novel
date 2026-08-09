# 时间轴改为竖向排列 — 设计文档

> 目标：把"时间轴"Tab 从横向滚动（章节为列，事件横排卡片）改为竖向时间轴（左侧竖线贯穿，
> 章节为大节点、事件为小节点+卡片，自上而下排列），交互行为不变，仅改动展示层。

日期：2026-08-09
状态：设计已批准，待实施
关联文档：无（独立小改动）

---

## 1. 背景与现状

`frontend/src/components/tabs/TimelineTab.jsx` 是"时间轴"Tab 的实现：

- `getTimeline(id)` 拉取全书事件列表 `events`，按 `chapter_id` 分组为 `groups`（第 56-64 行）。
- 当前渲染（第 66-95 行）：外层 `flex gap-6 overflow-x-auto`，每个章节是一个 flex-shrink-0 的
  列，列内部再用 `flex gap-2` 把该章节的事件卡片横向并排，整体靠横向滚动查看全书。
- 点击事件卡片调用 `setSelected(...)`（本地 `useState`，第 7 行），触发 `useEffect`
  （第 15-33 行）把详情 JSX 通过 `setRight(...)` 推送到 `AppShell` 右侧栏；再次点击同一张卡片
  会取消选中（`selected?.seq === e.seq ? null : e`，第 80 行）。
- 选中态样式：`border-seal-600 bg-seal-100/30`（第 82-85 行），未选中为
  `border-ink-300 bg-white`。
- `<main>` 容器（`AppShell.jsx:67`）本身已有 `overflow-y-auto`，纵向内容变长时无需额外处理
  滚动容器。

**问题**：横向滚动在事件/章节较多时不便浏览，且与页面其它 Tab（人物、故事等）的纵向阅读习惯
不一致。经与用户确认，改为经典的"竖线+圆点"竖向时间轴（章节为大节点，事件为小节点+卡片）。

## 2. 改动方案

**仅修改 `frontend/src/components/tabs/TimelineTab.jsx` 一个文件**，`selected`/
`setSelected`/`setRight` 的状态与交互逻辑完全不变，`groups` 的分组计算（第 56-64 行）不变。
只替换第 66-95 行的渲染部分。

### 2.1 提示文案

```jsx
<p className="mb-4 text-sm text-ink-600">
  按章节顺序自上而下排列的关键情节事件，点击卡片查看详情。
</p>
```

去掉"横向滚动查看"的措辞。

### 2.2 竖向时间轴结构

```jsx
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
```

要点：
- 竖线用外层容器的 `border-l-2 border-ink-300` 实现，不用绝对定位的伪线，结构更简单。
- 章节节点：`pine-600` 圆点（18px，含 3px 边框营造"挖孔"效果），与人物 Tab 里代表分类的色块
  风格呼应；事件节点：默认 `ink-300` 小圆点（10px），选中时变为 `seal-600`，与卡片高亮同步。
- 圆点用 Tailwind 任意值（`-left-[29px]` 等）定位，需与 `border-l-2`（2px 线宽）+
  `pl-6`（24px 内边距）的几何关系匹配，实现时以浏览器实际渲染效果为准做像素级微调，不必与
  上面代码里的数值完全一致。
- 点击卡片切换选中/取消选中的逻辑（`setSelected(isSelected ? null : e)`）与原实现完全一致，
  只是把原来内联判断 `selected?.seq === e.seq` 提前到 `isSelected` 变量，供圆点和卡片两处
  共用，避免重复计算。

### 2.3 外层容器

原来的 `<div className="px-8 py-10">` 外层容器保留，内部替换为 2.2 的结构，不再需要
`overflow-x-auto`。

## 3. 边界情况

- **事件很多、整体很长**：交给 `<main>` 已有的 `overflow-y-auto` 处理，无需新增滚动容器或
  虚拟化（沿用现状，未来若性能成为问题可再优化，本次不处理）。
- **某章节只有 1 个事件**：结构天然适配（`g.events.map` 只渲染一项），不需要特殊分支。
- **空状态/加载中/报错态**：完全不变，现有的三个 early-return 分支（第 35-54 行）保持原样。
- **圆点像素定位在不同章节标题长度下是否对齐**：由于圆点用 `absolute` 相对每个 chapter/event
  容器定位，不依赖标题文字长度，理论上不受影响；实施时用 `npm run dev` 肉眼检查多个章节/事件
  长度不同的真实数据来确认对齐效果。

## 4. 测试

项目前端无自动化测试框架（沿用现状），仅做手动验证：

1. `cd frontend && npm run dev`，打开某个已处理作品的"时间轴"Tab。
2. 确认整体呈竖向排列：左侧一条竖线，章节标题旁有大圆点，事件卡片自上而下堆叠，无横向滚动条。
3. 点击一个事件卡片，确认卡片变为高亮态（红色边框+浅红背景），对应圆点变为红色，右侧详情面板
   显示该事件信息；再次点击同一张卡片，确认取消选中、圆点变回默认灰色。
4. 滚动页面，确认整页可以正常纵向滚动查看全部章节和事件（依赖 `<main>` 已有的
   `overflow-y-auto`，本次改动不新增滚动容器）。
5. 用一本事件较多、章节较多的作品测试，确认竖线、圆点在不同章节标题长度下对齐正常，无明显
   错位或重叠。
6. `npx vite build`，确认构建无报错。
