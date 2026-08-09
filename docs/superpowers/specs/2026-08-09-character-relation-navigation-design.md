# 人物关系列表可点击跳转 — 设计文档

> 目标：在"人物"Tab 的关系列表中，把对方人物姓名变为可点击项，点击后右侧详情面板
> 切换到该人物自己的详情（姓名/描述/关系列表/出场章节），无需新增状态、组件或后端改动。

日期：2026-08-09
状态：设计已批准，待实施
关联文档：无（独立小改动，不涉及 `2026-07-27-novel-knowledge-graph-design.md` 的任何章节）

---

## 1. 背景与现状

`frontend/src/components/tabs/CharactersTab.jsx` 是"人物"Tab 的实现：

- 左侧渲染 `pkg.main_characters`（`mains`）卡片网格，点击卡片调用 `setSelectedId(c.id)`（本地
  `useState`，第 7 行）。
- 一个 `useEffect`（依赖 `[selectedId, graph, events]`，第 19-77 行）根据 `selectedId` 从
  `graph.json`（`getGraph(id)` 拉取）里查找该人物节点、计算其关系列表 `relations`，并通过
  `setRight(...)` 把详情 JSX 推送到 `AppShell` 的右侧栏。
- `relations` 的计算（第 27-34 行）：过滤出所有 `source`/`target` 命中 `selectedId` 的边，
  对每条边算出 `otherId`（对方节点 id），再反查 `graph.nodes` 得到 `other.label`（对方姓名），
  最终只保留 `{ label, category }` 两个字段——**`otherId` 在计算过程中已经拿到，但被丢弃了**。
- 关系列表渲染（第 51-66 行）：`<li>→ {r.label}（{r.category}）</li>`，纯文本，无任何点击/hover
  交互。

**问题**：用户想从关系列表里的"法正"直接跳到法正自己的详情，但目前只能回到左侧卡片网格，
如果法正恰好不在 `main_characters` 里，甚至没有入口能看到他的详情。

`graph.json` 的边（`edges`/`links`）的 `source`/`target` 存的是节点 id（如 `n2`/`n11`），不是
姓名（详见 AGENTS.md 关于 `graphify` node id 的说明）；姓名到 id 的反查已经在 `relations` 计算
里现成完成，不需要新建任何映射表。

## 2. 改动方案

**仅修改 `frontend/src/components/tabs/CharactersTab.jsx` 一个文件**，复用现有的
`selectedId`/`setSelectedId` 状态和渲染逻辑，不新增状态、不新增组件、不改后端、不改路由。

### 2.1 保留 `otherId`

```js
const relations = edges.map((e) => {
  const otherId = e.source === selectedId ? e.target : e.source;
  const other = graph?.nodes?.find((n) => n.id === otherId);
  return { label: other?.label || otherId, category: e.category, otherId };
});
```

（只在返回对象里多加一个已算好的 `otherId` 字段，不改变现有查找逻辑。）

### 2.2 关系列表姓名变为可点击按钮

```jsx
<ul className="mt-2 space-y-1.5">
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
</ul>
```

点击后 `selectedId` 变化 → 现有 `useEffect`（第 19-77 行）自动重新计算并 `setRight(...)`，右侧
详情面板切换为对方人物的信息，包括对方自己的关系列表和出场章节——**完全复用现有渲染路径，
无需为"对方人物"写任何新的渲染分支**。

### 2.3 样式

沿用项目里其它可点击文字的统一 hover 规范（`text-ink-900 hover:text-seal-600 hover:underline`，
与 `SuggestedQuestions.jsx`、`ReaderPage.jsx` 里"返回首页"链接等一致），不引入新的视觉语言。

## 3. 边界情况

- **对方人物不在 `main_characters` 卡片网格里**（例如是配角）：点击后详情仍能正常展示，因为
  详情面板是从完整的 `graph.nodes` 反查节点信息，并不局限于 `mains` 列表；左侧卡片网格里不会
  有对应的高亮项，这是预期表现，不做特殊提示或跳转到卡片位置。
- **`other` 反查失败**（数据缺失导致找不到对应节点）：沿用既有 fallback
  `other?.label || otherId`（显示原始节点 id），这是已存在的行为，本次改动不处理。
- **不提供"返回上一个"导航**：用户可随时从左侧卡片网格重新选择任意人物，经确认无需历史栈或
  返回按钮。
- **自引用/重复关系边**：不在本次改动范围内，维持现状（沿用现有 `.filter`/`.map` 结果，重复边
  会渲染多条列表项，这是既有行为）。

## 4. 测试

项目前端无自动化测试框架（沿用现状，`AGENTS.md` 未列出前端测试命令），仅做手动验证：

1. `cd frontend && npm run dev`，打开某个作品的"人物"Tab。
2. 点击左侧任意人物卡片，确认右侧关系列表中的人名显示为可点击样式（默认深灰，hover 变主题色
   并出现下划线）。
3. 点击关系列表中的一个人名，确认右侧详情面板切换为该人物的信息（姓名/描述/关系列表/出场
   章节均正确更新）。
4. 若该关系列表中存在不属于"主要人物"卡片网格的对方人物，点击后确认详情仍正常显示，左侧卡片
   网格无对应高亮（预期行为，非 bug）。
5. 从新详情的关系列表中点回原来那个人物，确认可以正常来回切换。
6. `npx vite build`，确认构建无报错。
