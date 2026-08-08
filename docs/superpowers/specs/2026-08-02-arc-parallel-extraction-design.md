# 分区并行抽取 + 跨区合并 — 设计文档

> 目标：把当前单流串行的抽取管线改造成「按情节线分区 → 并行抽取 → 跨区合并」，
> 让超长篇（500~1000+ block）的处理时间从数小时降到 20 分钟以内（先快），
> 同时通过两级合并保证人物图质量不滑坡（后好）。
> 方案 B（arc 分区并行），进程内 asyncio 并发，不引入外部基建。

日期：2026-08-02
状态：设计已批准，待实施
关联文档：`2026-07-27-novel-knowledge-graph-design.md`（§4 提取层、§5 数据模型、§8 错误处理）

---

## 1. 背景与目标

### 1.1 现状瓶颈

整条管线的墙钟时间几乎全部花在抽取阶段（`pipeline/extract.py`）：

- `extract_all` 依赖**全局滑动上下文**（`merge.py:184` `known_entities_prompt`）：
  每个 block 的 prompt 要注入「此前所有 block 已识别的人物」，因此只能**按序分窗口**处理
  （每窗口最多 `EXTRACT_CONCURRENCY=5` 个并发）。
- 500~1000 block 的超长篇 = 100~200 轮串行 LLM 往返，跑数小时是常态。
- `summarize` 阶段另有 4 个**串行** LLM 调用（spine → layered → cards → questions），
  是不小的固定尾延迟。

### 1.2 目标

- 超长篇（500~1000 block）端到端 ≤ 20 分钟。
- 抽取质量不下降：局部滑动上下文保留（arc 内），跨区身份由合并阶段补齐。
- 模型分层：便宜快模型做海量抽取，强模型做合并确认与分层摘要。
- 不引入任务队列/Celery 等外部基建；进程内 asyncio 并发。
- 保持现有「pipeline never raises」承诺与状态上报结构，前端无感。

### 1.3 明确的非目标（本期不做）

- **API 限流自适应**（429 感知、AIMD 动态并发、token bucket）——已讨论出方案（L1~L6），
  本期只保留现有固定并发 + 指数退避，限流治理作为下一迭代。
- 分布式 worker 横向扩展。
- 抽取阶段的 Agent 化（带工具的 strands Agent 抽取）。

---

## 2. 总体设计：改动前后对比

```
现状（单流串行）：
  parse → chunk → extract(全局滑动上下文, 串行窗口, 并发5)
                 → graphify建图 → summarize(4个串行LLM调用) → done

目标：
  parse → chunk → 分区(K个arc, 连续章节窗口 + 全局锚点种子)
                 → [arc0∥arc1∥…∥arcK-1 并行抽取, 每arc自带局部上下文]
                 → 跨区合并(确定性消重 → 强模型确认存疑候选)
                 → 统一registry → graphify建图 → summarize(部分并行) → done
```

关键洞察：**并行提速的真正来源是把全局顺序依赖拆掉**（每个 arc 独立上下文），
提高并发只有在依赖被拆掉后才变得有意义。多线程/并发是执行机制，arc 分区是组织单元。

---

## 3. 分区器（新文件 `pipeline/partition.py`）

### 3.1 接口

```python
def partition_blocks(blocks: list[Block], arc_blocks_target: int = ARC_BLOCKS_TARGET) -> list[list[Block]]
def scan_global_anchors(blocks: list[Block], top_n: int = ARC_ANCHOR_COUNT) -> str
```

### 3.2 分区规则

- `K = clamp(ceil(N / arc_blocks_target), MIN_ARC, MAX_ARC)`，默认 `arc_blocks_target=60`、
  `MIN_ARC=2`、`MAX_ARC=16`。500~1000 block → 约 9~17 个 arc。
- 分区只按**章节边界**切，章节绝不被劈开：把章节按 block 累计数分摊到各 arc，
  使各 arc 的 block 数尽量均衡（允许最后一个 arc 略少）。
- 分区是**纯确定性**操作（无 LLM），可单测。

### 3.3 全局锚点种子

- 复用 `fake_extract_block` 的 CJK n-gram 频率统计逻辑（纯正则、秒级、零 LLM 成本），
  把 2-4 字 CJK 子串按（频率, 长度）排序，贪心保留高频长名并抑制已被覆盖的子串，
  得到全书 top-N 人名。该计数逻辑从 `fake_extract_block` 中**抽成共享函数**，
  放 `partition.py`（`fake_extract_block` 改调它，行为不变）。
- `scan_global_anchors` 输出 top-`ARC_ANCHOR_COUNT`（默认 20）人名的提示块，作为
  每个 arc 首个窗口的「已知角色」注入，让跨 arc 的代词/别名解析有一半是稳的。
- **上下文安全说明**：每次 LLM 调用只看到「当前 1 个 block 的正文 + ≤40 条已知实体摘要」，
  约 3.8K token，不随 arc 长度增长。80 block/arc 不会撑爆上下文。
  arc 大小是**并行粒度与合并规模**的取舍，不是上下文问题。

---

## 4. 并行 arc 抽取（改写 `pipeline/extract.py`）

### 4.1 接口

```python
async def extract_arcs(
    blocks: list[Block],
    granularity: str = "quick",
    work_dir: Optional[Path] = None,
    progress_cb=None, warn_cb=None,
) -> list[EntityRegistry]
```

- `extract_arcs` 内部：`partition_blocks` → 为每个 arc 起一个协程 → `asyncio.gather` 全部并行。
- **保留**现有 `extract_all`（单流版）作为等价性测试的基线与新结构的薄封装，
  二者共享同一 `run_block` / `_build_prompt` 核心逻辑。

### 4.2 每个 arc 的 worker

- 每个 arc 一个**独立 `EntityRegistry`** + 局部滑动上下文，完全复用现有机制
  （`known_entities_prompt`、`_build_prompt`、`run_block` 的退避重试）。
- arc 内部仍按窗口串行推进以保持上下文新鲜；首个窗口的 `known` 用
  `anchor_prompt + registry.known_entities_prompt()`，之后由 arc 自身 registry 接管。
- 所有 arc 共享一个进程级 `asyncio.Semaphore(GLOBAL_EXTRACT_CONCURRENCY)`（默认 20），
  确保全管线在途 LLM 调用总数有界（rate-limit 正式治理前的临时护栏）。
- fake 模式行为不变：`fake_extract_block` 与 anchors/上下文无关，仍确定性。

### 4.3 每 arc 结果落盘（耐久 + 可调试）

- 每个 arc 完成后把 {characters, places, relationships, events} 序列化到
  `data/works/{work_id}/arcs/arc_{i:02d}.json`。
- 中途崩溃不丢已抽部分；merge 失败时可用它重放。文件很小，成功流程也保留。
- 结构照搬 `registry.events` / `CharacterRecord` / `RelationRecord` 的可序列化字段。

---

## 5. 跨区合并（增强 `pipeline/merge.py`）

### 5.1 接口

```python
def merge_arcs(arc_registries: list[EntityRegistry], *, confirm: bool = True) -> EntityRegistry
```

两级，先便宜后贵。这正是原 `merge.py` 注释里 "queued for a batched LLM
normalization confirm" 那句**从未实现**的功能落点。

### 5.2 第一级：确定性合并（免费）

- 依次把每个 arc registry 的实体汇入一个 master `EntityRegistry`，
  完全复用现有 `add_character` / `add_place` / `add_relationship`：
  精确名匹配 → alias 表 → difflib≥0.86 模糊匹配自动归并。events 按顺序拼接
  （`order_hint` 已是全局序）。这一级消掉绝大多数跨 arc 同名/近名重复。

### 5.3 第二级：强模型确认（有界、可选）

- **候选筛选**（确定性，无 LLM）：master 中满足以下任一条件的角色记录进入候选：
  1. 出现在 ≥2 个 arc；或
  2. 与其他记录的规范化名相似度在 [0.6, 0.86)（近名但够不上自动合并）。
- **批量确认**：把候选按 ~25-30 条一批，喂给**强模型**（`tier="strong"`），
  每条只给「规范名 + 别名 + 一行身份描述 + 出现 arc 列表」，**不喂全文**，输入有界。
  模型输出合并判定 `[[nameA, nameB, ...], final_name, ...]`。
- **应用**：按判定把候选并入 master（更新规范名、alias 表、合并 mention_count，
  并把该名相关的 relationship 的 source/target 一并改写）。
- **降级**：fake 模式或强模型调用失败 → 跳过第二级，仅用确定性合并（warn_cb 记录）。

### 5.4 失败隔离

- merge 全程 try/except；失败只退回确定性合并，不 raise，不污染已生成的状态。

---

## 6. 双模型分层（`config.py` + `pipeline/llm.py`）

### 6.1 新配置项

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `NOVEL_KG_ARC_BLOCKS_TARGET` | `60` | 每 arc 目标 block 数 |
| `NOVEL_KG_MIN_ARC` | `2` | arc 数下限 |
| `NOVEL_KG_MAX_ARC` | `16` | arc 数上限 |
| `NOVEL_KG_ARC_ANCHOR_COUNT` | `20` | 全局锚点 top-N 人名 |
| `NOVEL_KG_GLOBAL_EXTRACT_CONCURRENCY` | `20` | 全管线在途抽取调用上限 |
| `NOVEL_KG_STRONG_MODEL_ID` | `""` | 强模型 id；为空则强==快 |
| `NOVEL_KG_STRONG_LLM_PROVIDER` | `LLM_PROVIDER` | 强模型 provider |

### 6.2 llm.py 改动

- `structured_output(schema, prompt, *, system_prompt, what, attempts, tier="fast")`
  新增 `tier` 参数；`make_model` / `make_agent` 增加对应 `tier`/model_id 解析。
- 抽取阶段全部走 `tier="fast"`；merge 确认、spine、layered 走 `tier="strong"`。
- **重试收敛**：把 `extract.py` 外层与 `llm.py` 内层两套重试合并到 llm 层一处
  （消除现状 4×3=12 次叠加），`extract.py` 只保留调用层的尝试。
- `STRONG_MODEL_ID` 为空时 strong tier 退回 fast 配置，未配分层也能跑（渐进默认）。

---

## 7. summarize 并行化（`pipeline/summarize.py`，小改）

- `_llm_summary` 的串行链改成：spine（strong）→ 就绪后 **layered / cards / questions
  三个调用并行**（`concurrent.futures.ThreadPoolExecutor(max_workers=3)`）。
- `summarize()` **签名不变、保持同步**（fake 路径零改动；真实路径内部线程池并行），
  调用方（orchestrator / 测试）无需改动。
- cards / questions 失败仍各自独立兜底（现状逻辑保留）。

---

## 8. orchestrator 改动（`pipeline/orchestrator.py`）

- 抽取阶段：`extract_all` → `await extract_arcs(...)` + `merge_arcs(regs)`（merge 为阻塞调用，
  在异步上下文用 `asyncio.to_thread` 包一层）。
- 进度上报：phase 仍为 `extracting`，`progress = 已抽block总数 / block总数`，
  `message = f"抽取中 arc {i+1}/{K} (block {done}/{total})"`。
- 合并完成后照旧 `events.json` 落盘（§4.3 时序不变）→ graphify → summarize。
- 其余函数签名、`status.json` 结构、失败写 failed 的逻辑**不变**。

---

## 9. 状态上报 / 失败隔离 / 耐久性（保持现有承诺）

- 单 arc 失败 → 该 arc 标记 warning、以空 registry 继续，**不拖垮整本**；
  若全部 arc 失败 → 照旧 raise ParseError → status=failed。
- 合并失败 → 仅退回确定性合并 + warning。
- 全程不 raise 未捕获异常；异常路径写入 status.error。
- 抽取结果每 arc 落盘，merged events 照旧在抽取后立即持久化。

---

## 10. 完全不变的部分

- `pipeline/parse.py`、`pipeline/chunk.py`、`pipeline/graph.py`、`pipeline/ask.py`
- `app/routes.py`、`app/models.py`、`store.py`、fake 抽取/摘要路径
- 前端（`PHASE_*`、`CATEGORY_*` 等常量不动）

---

## 11. 测试策略

- **分区器单测**（`test_partition.py`）：章节不被劈开；K 在 [MIN,MAX] 内；总 block 数守恒；
  anchor 扫描确定性返回 top 名。
- **合并单测**（`test_merge_arcs.py`）：两个含共同人物的合成 arc registry →
  确定性合并后为 1 个节点；alias 合并；关系归并；候选列表筛选正确；
  强模型确认路径（mock 掉）应用合并。
- **等价性测试**（并入 `test_pipeline_integration.py`）：fake 模式下同一输入，
  `extract_arcs`+`merge_arcs` 与单流 `extract_all` 产出**相同的规范化节点集与边集**
  （比较排序后的 node label 集合与 edge key 集合，容忍规范名选取顺序差异）。
- 现有全部测试保持通过。

---

## 12. 目录结构改动

```
backend/app/pipeline/
  partition.py        # 新增：分区 + 全局锚点扫描
  extract.py          # 改写：extract_arcs（并行）+ 保留 extract_all（基线）
  merge.py            # 增强：merge_arcs（两级合并）
  llm.py              # 增强：tier 参数 + 重试收敛
  summarize.py        # 小改：spine→并行(layered, cards, questions)
  orchestrator.py     # 改写：接入 extract_arcs + merge_arcs
backend/tests/
  test_partition.py   # 新增
  test_merge_arcs.py  # 新增
  test_pipeline_integration.py  # 增加等价性测试
```

---

## 13. 后续迭代（不在本期）

- 限流自适应（L1~L6：429 感知、Retry-After、AIMD 动态并发、预算模型、全局共享限流器）。
- Review agent：抽取/摘要一致性复核（对应 graphify AMBIGUOUS 思路）。
- 章节摘要与 beat 故事预生成并行化（让按需点击零延迟）。
- 跨 arc 分区改为按真实情节线聚类（本期的连续章节窗口是第一步）。
