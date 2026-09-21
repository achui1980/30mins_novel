// 关系图谱页 (design §5)。在原有 8 类图例 / 地点裁剪 / 右栏详情之上接入时间维度：
// 章节滑块、基于 hidden 的可见性过滤、关系演变高亮、右栏出场曲线、旧版本降级横幅。
//
// **拖动滑块只做 DataSet 的 update({id, hidden})，绝不调 setData。**
// 已对着 vis-network 9.1.13 的源码确认过这条路径：
//   DataSet.update -> NodesHandler/EdgesHandler.update -> Node/Edge.setOptions
//   （options.hidden !== undefined 时返回 true）-> emit("_dataChanged")
//   -> emit("_dataUpdated") -> Network._updateVisibleIndices()
//                              + _updateValueRange(nodes/edges) + _requestRedraw
// 全程不碰 node.x/y，坐标稳定，代价是 O(变化量)。而 Network.setData 会先
// emit("resetPhysics") + emit("_resetData")，布局从头重跑、拖过的位置全丢。
//
// 另外 _updateVisibleIndices 里边的可见性判定是：
//   edge.options.hidden === false && fromNode.options.hidden === false
//                                 && toNode.options.hidden === false
// 也就是说**端点被隐藏的边 vis-network 会自己一起隐掉**，这里不需要额外处理。
// 这一点很重要：merge 阶段会给关系补章节计数而不补端点的提及计数，所以一条边的
// first_chapter 可以**早于**它两端节点的 first_chapter（节点与边各自独立算 hidden），
// 靠 vis 的这条规则才不会出现「悬空的边」。
//
// ──── 上面那条链子少写了一步，而少写的这一步正是最容易被"优化"掉的 ────
// （行号均对 node_modules/vis-network/standalone/umd/vis-network.js @ 9.1.13）
//
// **物理不变式**：_dataUpdated 的处理函数除了 _updateVisibleIndices + _requestRedraw，
// 还会 `emit("startSimulation")`（:36151）—— 也就是说滑块**每动一格**，力导向模拟
// 都会被重新点起来。它无害**只是因为**物理成员资格是按 `options.physics === true`
// 判定的，**不看 hidden**（:25226 节点 / :25235 边）：被隐藏的节点和边依然完整地留在
// 力场里，力场在 hidden 翻转前后完全相同，所以当前布局本来就已经是这个力场的不动点，
// 重启的模拟原地收敛，一个节点都不会动。
//   ⚠️ **推论（改之前必读）**：如果谁以后为了省算力给隐藏的条目加上 `physics: false`，
//   力场就**真的变了** —— 剩下的节点会重新找平衡，拖滑块开始让整张图重新铺开，
//   正好毁掉「用 hidden 而不用 setData」这整个设计唯一要保住的 UX 性质（节点位置稳定）。
//   换句话说那个"优化"会从另一条路重新引入我们花力气绕开的 setData 行为。
//
// **_updateValueRange 为什么可以不管**：同一个 _dataUpdated 处理函数里，紧挨着
// _updateVisibleIndices 还会跑 _updateValueRange(body.nodes) / (body.edges)
// （:36148-36149，和 startSimulation 同一批）。它在这里是**空转**的：它只读
// getValue() 也就是 options.value（:20200 节点 / :23067 边），而下面的节点大小走
// `size`、边粗细走 `width`，**从不设 value**，于是 valueMin/valueMax 恒为
// undefined，setValueRange 一个条目都不会被调到。退一步说即便将来改用 value，
// hidden 也仍然不影响它：_updateVisibleIndices 重建的是 body.nodeIndices /
// body.edgeIndices（:36103-36104）这两张**另外的**索引表，被隐藏的条目依旧完整
// 留在 body.nodes / body.edges 里，取值范围在 hidden 翻转前后完全相同。
//
// **浅合并不变式**：DataSet._updateItem 是 `{...item, ...update}` 的**浅合并**（:15843），
// 所以 update({id, hidden}) 只覆盖 hidden，条目上挂的 _raw / _transition 原样留下 ——
// 这正是每个条目的 _raw 载荷能活过任意多次 hidden 补丁的原因。
// 如果它是 replace 语义，下一轮 diff 读到的就是 `_raw === undefined`，
// firstChapterOrder 拿不到 first_chapter 就返回 0，isVisibleAt 对任何东西都返回 true，
// 于是过滤器会**静默地把整张图重新显示出来**（不报错、不空图，只是过滤失效）。

import { useEffect, useMemo, useRef, useState } from "react";
import { getGraph, reanalyzeWork } from "../../api";
import {
  CATEGORY_ORDER,
  EVOLUTION_EDGE_DASHES,
  categoryColor,
  evolutionBadge,
} from "../../constants";
import ChapterSlider from "../graph/ChapterSlider";
import MentionSparkline from "../graph/MentionSparkline";
import {
  buildTimeline,
  isVisibleAt,
  mentionBars,
  mentionPeak,
  pairKey,
} from "../../lib/graphTimeline";

const PLACE_TOP_N = 15;

// vis-network 只吃原始色值（拿不到 Tailwind token），和下面地点节点的 #d9d9d9 同理。
// 颜色取自 CATEGORY_COLORS["敌人"]，视觉上和演变的"冲突感"一致。
const EVOLUTION_LABEL_FONT = { size: 11, color: "#6B2E2E", strokeWidth: 3 };

/**
 * 演变徽章文案的唯一出口：图上的边标签和右栏标题共用这一个函数，
 * 不各写一遍 `confirmed ? ... : ...`。没有演变时返回空串。
 */
export function transitionBadgeText(transition) {
  return transition ? evolutionBadge(transition.confirmed) : "";
}

/**
 * 某个演变 step 是否还在当前 cutoff **之后**（右栏里要画淡 = 还没发生）。
 *
 * 章节先后只以 orderMap 为准 —— 绝不比较 chapter_id 字符串（chNNNN 的字典序
 * 恰好等于章序是零填充的巧合，不是契约）。
 *
 * 两个边界都刻意不兜 0：
 *  - cutoff 不是有限数（Infinity = 没有分档 / 旧版本作品 = 读完全书）时没有"之后"，
 *    一律不画淡；
 *  - step 的章节在 orderMap 里查不到时按"尚未发生"处理并画淡。给未知章节兜 0
 *    会把它渲染成实心，等于断言"这一步已经发生了" —— 错在更危险的方向。
 */
export function isStepAfterCutoff(step, orderMap, cutoff) {
  if (!Number.isFinite(cutoff)) return false;
  const order = orderMap && orderMap.get(step && step.chapter_id);
  if (!Number.isFinite(order)) return true;
  return order > cutoff;
}

/**
 * 边数组的唯一出口。
 *
 * **真实产物里这个键叫 `links`，不叫 `edges`** —— graphify 的 to_json 输出的是
 * networkx node-link 形状。对着 data/works/t17verify0001/graph.json 核过：顶层键是
 * `['directed','multigraph','graph','nodes','links','hyperedges',...]`，**没有 edges**。
 * 而仓库里的手写夹具/示例用的是 `edges`，所以两种键名都得吃。
 *
 * 去掉 `|| graph.links` 这一支的后果不是抛错、不是空图，而是**每一张真实图谱都静默地
 * 渲染成零条边**：节点全在、图例照画、滑块照常动、右栏节点卡片照常弹 —— 看起来
 * 完全正常，只是关系全没了。没有任何运行时症状会把它暴露出来，所以这两种键名在
 * GraphTab.test.js 里各自被独立钉住。
 */
export function edgeList(graph) {
  return graph?.edges || graph?.links || [];
}

export default function GraphTab({ id, setRight, onViewChapter }) {
  const containerRef = useRef(null);
  const nodesDsRef = useRef(null);
  const edgesDsRef = useRef(null);
  const cutoffRef = useRef(Infinity);
  // onViewChapter 从 ReaderPage.jsx:61 以**普通函数**传进来（不是 useCallback），
  // 每次 render 都是新身份。放进右栏 effect 的依赖会让右栏每帧重建；省略它又是个
  // 按构造成立的 stale closure。用 ref 拿"当下最新的一份"，effect 就既不用依赖它、
  // 也不会读到旧的 —— 依赖数组因此可以写全，不需要 eslint 抑制。
  const onViewChapterRef = useRef(onViewChapter);
  useEffect(() => {
    onViewChapterRef.current = onViewChapter;
  }, [onViewChapter]);

  const [graph, setGraph] = useState(null);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [showAllPlaces, setShowAllPlaces] = useState(false);
  const [bucketIdx, setBucketIdx] = useState(0);
  // 网络重建计数：重建后 DataSet 是新的，hidden 同步必须重跑一次。
  const [built, setBuilt] = useState(0);
  const [reanalyzeMsg, setReanalyzeMsg] = useState("");

  useEffect(() => {
    getGraph(id).then(setGraph).catch((e) => setError(e.message));
  }, [id]);

  const edges = useMemo(() => edgeList(graph), [graph]);

  // 时间轴的**唯一**入口。刻意不分别调 buildChapterOrder / buildBuckets：
  // 前端还存在另一份形状不同的章节列表（layered_summary.chapters 是
  // `{chapter, summary}`，没有 id / order，而且只覆盖一小部分章节），喂错那一份
  // 不会报错，只会得到空的 orderMap / buckets —— 时间轴看着在但什么都不过滤。
  // buildTimeline(graph) 让「拿错章节列表」在调用点就不可表达。
  const timeline = useMemo(() => buildTimeline(graph), [graph]);
  const { hasTimeline: timelineOn, chapters, orderMap, buckets, transitionIndex } = timeline;

  // chapter_id -> 标题，只用于显示（不是章序，章序一律走 orderMap）。
  const chapterTitles = useMemo(() => {
    const map = new Map();
    for (const c of chapters) map.set(c.id, c.title || c.id);
    return map;
  }, [chapters]);

  // 默认停在最后一档（全书），符合"上帝视角"的产品意图。
  useEffect(() => {
    setBucketIdx(buckets.length > 0 ? buckets.length - 1 : 0);
  }, [buckets]);

  // 一档的 cutoff 是档内**末章**的 order（见 buildBuckets 注释）。
  // 没有分档时用 Infinity = 全部可见，这正是旧版本作品的降级行为。
  const cutoff = useMemo(() => {
    if (buckets.length === 0) return Infinity;
    const bucket = buckets[Math.min(bucketIdx, buckets.length - 1)];
    return bucket ? bucket.cutoff : Infinity;
  }, [buckets, bucketIdx]);

  // 建网是异步的（动态 import vis-network），建的时候要读到**当下**的 cutoff。
  cutoffRef.current = cutoff;

  const placeCount = useMemo(() => {
    if (!graph) return 0;
    return (graph.nodes || []).filter((n) => n.node_type === "place").length;
  }, [graph]);

  useEffect(() => {
    if (!graph || !containerRef.current) return;

    let cancelled = false;
    let network = null;

    async function buildNetwork() {
      const { DataSet, Network } = await import("vis-network/standalone");
      if (cancelled || !containerRef.current) return;

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
      const at = cutoffRef.current;

      // hidden 一律写成显式 boolean：vis 的 _updateVisibleIndices 用的是
      // `options.hidden === false` 严格比较，undefined 会走默认值那条路。
      const nodes = visibleNodes.map((n) => ({
        id: n.id,
        label: n.label,
        shape: n.node_type === "place" ? "box" : "dot",
        size: 12 + Math.min(20, (n.mention_count || 1) * 2),
        color:
          n.node_type === "place" ? { background: "#d9d9d9", border: "#b0b0b0" } : undefined,
        hidden: !isVisibleAt(n, at, orderMap),
        _raw: n,
      }));

      const visEdges = edges
        .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
        .map((e, i) => {
          // pairKey 与顺序无关，所以 (source,target) 和 (target,source) 命中同一条。
          const transition = transitionIndex.get(pairKey(e.source, e.target));
          return {
            id: `e${i}`,
            from: e.source,
            to: e.target,
            color: { color: categoryColor(e.category) },
            width: Math.max(1, Math.min(6, e.weight || 1)),
            arrows: e.directed ? "to" : undefined,
            dashes: transition ? EVOLUTION_EDGE_DASHES : undefined,
            label: transition ? transitionBadgeText(transition) : undefined,
            font: transition ? EVOLUTION_LABEL_FONT : undefined,
            hidden: !isVisibleAt(e, at, orderMap),
            _raw: e,
            _transition: transition || null,
          };
        });

      if (cancelled || !containerRef.current) return;

      const nodesDs = new DataSet(nodes);
      const edgesDs = new DataSet(visEdges);
      nodesDsRef.current = nodesDs;
      edgesDsRef.current = edgesDs;

      network = new Network(
        containerRef.current,
        { nodes: nodesDs, edges: edgesDs },
        {
          nodes: { font: { size: 15, face: "PingFang SC, Microsoft YaHei, sans-serif" } },
          edges: { smooth: { type: "continuous" } },
          physics: { stabilization: { iterations: 150 }, barnesHut: { springLength: 130 } },
          interaction: { hover: true, tooltipDelay: 120 },
        }
      );

      network.on("click", (params) => {
        if (params.nodes.length > 0) {
          const n = nodesDs.get(params.nodes[0]);
          setDetail({ type: "node", data: n && n._raw });
        } else if (params.edges.length > 0) {
          const e = edgesDs.get(params.edges[0]);
          setDetail({ type: "edge", data: e && e._raw, transition: e && e._transition });
        } else {
          setDetail(null);
        }
      });

      if (!cancelled) setBuilt((v) => v + 1);
    }

    buildNetwork();

    return () => {
      cancelled = true;
      nodesDsRef.current = null;
      edgesDsRef.current = null;
      if (network) network.destroy();
    };
    // 依赖数组是**完整**的，刻意不加 eslint 抑制：effect 闭包里的自由变量只有这五个
    // 反应式值，剩下的是 ref（豁免）、useState setter（规则已知稳定）和模块作用域的
    // 导入/常量/函数。
    // 不加抑制换来的好处只有一条，而且是**将来**才兑现的：万一以后谁重构这个
    // effect 时**漏写**一个依赖，装上 ESLint 后能被 react-hooks/exhaustive-deps 抓到；
    // 留着抑制注释则连这条都拿不到。今天它并没有在把关 —— 本仓库**完全没有 ESLint**
    // （没有配置文件、package.json 里没有这个依赖、node_modules/.bin 下也没有 eslint
    // 可执行文件），与 AGENTS.md 的「no lint/format/typecheck config」一致。
    //   ⚠️ 别把它当成身份稳定性的护栏：exhaustive-deps 只查依赖的**缺失与多余**，
    //   对「某个依赖每帧都是新身份」没有任何概念。orderMap / transitionIndex 已经
    //   老老实实列在下面了，所以将来谁让它们变得每帧新身份（比如把
    //   buildTimeline 的 useMemo 拆了），整张网络会被静默地反复重建，而 lint
    //   会一路放行。守住这件事的是 timeline 那个 useMemo 的记忆化本身，不是工具。
    // 注意这里**没有** cutoff —— 拖滑块绝不重建网络，只走下面的 hidden diff。
  }, [graph, edges, showAllPlaces, orderMap, transitionIndex]);

  // 拖动滑块：只批量改 hidden，绝不 setData（否则布局重跑、节点乱跳）。
  // 只 push 真正变化的条目，代价是 O(变化量)。
  useEffect(() => {
    const nodesDs = nodesDsRef.current;
    const edgesDs = edgesDsRef.current;
    if (!nodesDs || !edgesDs) return;

    const nodePatch = [];
    nodesDs.forEach((item) => {
      const next = !isVisibleAt(item._raw, cutoff, orderMap);
      if (next !== Boolean(item.hidden)) nodePatch.push({ id: item.id, hidden: next });
    });
    if (nodePatch.length > 0) nodesDs.update(nodePatch);

    const edgePatch = [];
    edgesDs.forEach((item) => {
      const next = !isVisibleAt(item._raw, cutoff, orderMap);
      if (next !== Boolean(item.hidden)) edgePatch.push({ id: item.id, hidden: next });
    });
    if (edgePatch.length > 0) edgesDs.update(edgePatch);
  }, [cutoff, orderMap, built]);

  // 右栏被**故意拆成两个** effect，因为两者的触发条件不同：
  //  - 占位文案只跟 detail 有关，不能跟着 cutoff 跑。合在一起时滑块每动一格都会
  //    重建一次占位 <div> 并 push 进父组件 state，换来一次
  //    GraphStack → StackShell → GraphTab 的重渲染和零像素的视觉变化。
  //  - 详情卡片必须跟着 cutoff 走（出场曲线的 cutoff、演变 step 的画淡都依赖它）。
  // 两个 effect 都调 setRight 不会打架：React 在一次 commit 里先跑完所有 cleanup
  // 再跑所有 body，且按声明顺序，所以任一时刻最后一次 setRight 都来自条件成立的那个。
  useEffect(() => {
    if (detail?.data) return undefined;
    setRight(<div className="text-sm text-ink-600">点击图谱中的节点或连线查看详情</div>);
    return () => setRight(null);
  }, [detail, setRight]);

  useEffect(() => {
    if (!detail?.data) return undefined;

    function jumpTo(location) {
      if (!location) return;
      const [chapterId, para] = String(location).split("#p");
      // 走 ref 而不是闭包里的 onViewChapter：见 onViewChapterRef 处的说明。
      onViewChapterRef.current?.(chapterId, para !== undefined ? Number(para) : undefined);
    }

    if (detail.type === "node") {
      // 曲线的可见性闸门用**本组件自己算的** bars/peak，和 MentionSparkline 内部
      // 的前提判断一致（peak<=0 时它自己返回 null）。这样将来谁把 props 接错了，
      // 会看到「提及 N 次」下面空出一块可见的窟窿，而不是静默地什么都不显示。
      // 刻意**不**用 mention_count>0 当闸门：只靠关系入场的人物 mention_count 是 1
      // 而 mentions_by_chapter 是 {}，地点节点也带 mention_count（真实数据里有个
      // mention_count=50 的地点）却通常没有 mentions_by_chapter —— 那种闸门会在
      // 正确代码上误报。
      const node = detail.data;
      const showSparkline =
        timelineOn && mentionPeak(mentionBars(node, chapters, cutoff)) > 0;
      setRight(
        <div>
          <h3 className="font-serif text-lg font-semibold text-ink-900">{node.label}</h3>
          {node.role && <p className="text-sm text-ink-600">{node.role}</p>}
          {node.description && <p className="mt-3 text-sm text-ink-900">{node.description}</p>}
          <p className="mt-4 text-xs text-ink-600">
            {node.node_type === "place" ? "地点" : "人物"} · 提及 {node.mention_count || 0} 次
          </p>
          {showSparkline && (
            <MentionSparkline node={node} chapters={chapters} cutoff={cutoff} />
          )}
        </div>
      );
    } else {
      const transition = detail.transition;
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

          {transition && (
            <div className="mt-3 rounded-card border border-ink-300 bg-paper-100 p-3">
              <p className="text-xs font-semibold text-seal-600">
                {transitionBadgeText(transition)}
              </p>
              {!transition.confirmed && (
                <p className="mt-1 text-xs text-ink-600">（未经强模型确认，仅供参考）</p>
              )}
              {/* steps 已由后端按章序排好，这里不重排。 */}
              <ol className="mt-2 space-y-2">
                {(transition.steps || []).map((step, i) => {
                  const later = isStepAfterCutoff(step, orderMap, cutoff);
                  return (
                    <li key={`${step.chapter_id}-${i}`} className={later ? "opacity-40" : ""}>
                      <p className="text-sm text-ink-900">
                        {chapterTitles.get(step.chapter_id) || step.chapter_id} · {step.category}
                      </p>
                      {step.evidence && (
                        <>
                          {/* evidence 是这段关系的代表性原文（最长的一条），
                              **不保证出自这一步所在的章**，所以绝不能写成
                              「第N章原文」。 */}
                          <p className="mt-1 text-xs text-ink-600">关系证据（未必出自该章）</p>
                          <p className="mt-0.5 text-xs italic text-ink-600">「{step.evidence}」</p>
                        </>
                      )}
                      <button
                        type="button"
                        onClick={() => jumpTo(step.chapter_id)}
                        className="mt-1 text-xs text-ink-600 hover:text-seal-600 hover:underline"
                      >
                        查看原文 →
                      </button>
                    </li>
                  );
                })}
              </ol>
            </div>
          )}

          {detail.data.detail && <p className="mt-3 text-sm text-ink-900">{detail.data.detail}</p>}
          {detail.data.evidence && (
            <p className="mt-3 text-sm italic text-ink-600">「{detail.data.evidence}」</p>
          )}
          {detail.data.source_location && (
            <button
              type="button"
              onClick={() => jumpTo(detail.data.source_location)}
              className="mt-2 text-xs text-ink-600 hover:text-seal-600 hover:underline"
            >
              查看原文 →
            </button>
          )}
        </div>
      );
    }
    return () => setRight(null);
    // 依赖数组同样是完整的（onViewChapter 走 ref，不进依赖），所以这里也没有抑制。
  }, [detail, chapters, chapterTitles, cutoff, orderMap, timelineOn, setRight]);

  async function onReanalyze() {
    setReanalyzeMsg("正在提交…");
    try {
      await reanalyzeWork(id);
      setReanalyzeMsg("已提交重新分析，可在处理页查看进度。");
    } catch (e) {
      setReanalyzeMsg(e.message || "重新分析失败");
    }
  }

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

      {/* 顶层 chapters 在不在，是降级判定的**唯一**闸门（hasTimeline）。 */}
      {timelineOn ? (
        <div className="mt-4">
          <ChapterSlider buckets={buckets} value={bucketIdx} onChange={setBucketIdx} />
        </div>
      ) : (
        <div className="mt-4 rounded-card border border-ink-300 bg-paper-100 px-4 py-3">
          <p className="text-sm text-ink-900">该作品分析于旧版本，重新分析可解锁时间轴</p>
          <button
            type="button"
            onClick={onReanalyze}
            className="mt-2 rounded-btn bg-seal-600 px-3 py-1.5 text-sm text-white hover:bg-seal-700"
          >
            重新分析
          </button>
          {reanalyzeMsg && <p className="mt-2 text-xs text-ink-600">{reanalyzeMsg}</p>}
        </div>
      )}

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
