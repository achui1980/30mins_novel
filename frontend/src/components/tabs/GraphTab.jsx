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
