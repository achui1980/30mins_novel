import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Network } from "vis-network/standalone";
import { getWork, getGraph, graphHtmlUrl } from "../api";
import { CATEGORY_ORDER, categoryColor } from "../constants";

const TABS = [
  { key: "overview", label: "概览" },
  { key: "arcs", label: "故事脉络" },
  { key: "graph", label: "人物关系" },
  { key: "settings", label: "设定卡" },
];

export default function ReaderPage() {
  const { id } = useParams();
  const [pkg, setPkg] = useState(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("overview");

  useEffect(() => {
    getWork(id).then(setPkg).catch((e) => setError(e.message));
  }, [id]);

  if (error) {
    return (
      <div className="reader-container">
        <Link to="/" className="muted">← 返回首页</Link>
        <div className="error-banner" style={{ marginTop: 16 }}>{error}</div>
      </div>
    );
  }
  if (!pkg) {
    return (
      <div className="reader-container">
        <div className="empty"><span className="spinner" /> 加载中…</div>
      </div>
    );
  }

  const ls = pkg.layered_summary || {};

  return (
    <div className="reader-container">
      <div className="reader-header">
        <div>
          <Link to="/" className="muted">← 返回首页</Link>
          <h1 className="reader-title">{pkg.title}</h1>
        </div>
        <a href={graphHtmlUrl(id)} target="_blank" rel="noreferrer" className="btn ghost">
          完整图谱 ↗
        </a>
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`tab${tab === t.key ? " active" : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && <Overview ls={ls} pkg={pkg} />}
      {tab === "arcs" && <Arcs ls={ls} />}
      {tab === "graph" && <GraphTab id={id} />}
      {tab === "settings" && <Settings cards={pkg.setting_cards || []} />}
    </div>
  );
}

function Overview({ ls, pkg }) {
  const mains = pkg.main_characters || [];
  const questions = pkg.suggested_questions || [];
  return (
    <div>
      <div className="card">
        {ls.one_liner && <p className="one-liner">{ls.one_liner}</p>}
        {ls.overview && <p className="overview">{ls.overview}</p>}
      </div>

      <h2 className="section-title">主要人物</h2>
      {mains.length === 0 ? (
        <div className="empty">未识别到主要人物</div>
      ) : (
        <div className="grid cols">
          {mains.map((c) => (
            <div key={c.id} className="card char-card">
              <div>
                <span className="name">{c.label}</span>
              </div>
              {c.description && <div className="desc">{c.description}</div>}
              <div className="mention">提及 {c.mention_count} 次</div>
            </div>
          ))}
        </div>
      )}

      {questions.length > 0 && (
        <div className="questions">
          <h2 className="section-title">你可能想问（展示用）</h2>
          <div className="card">
            {questions.map((q, i) => (
              <div key={i} className="q-item">
                <div className="q">{q.question}</div>
                {q.rationale && <div className="r">{q.rationale}</div>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Arcs({ ls }) {
  const arcs = ls.arcs || [];
  const chapters = ls.chapters || [];
  return (
    <div>
      <h2 className="section-title">情节线</h2>
      {arcs.length === 0 ? (
        <div className="empty">未识别到情节线</div>
      ) : (
        <div className="grid">
          {arcs.map((a, i) => (
            <div key={i} className="card arc">
              <div className="arc-title">{a.title}</div>
              <div className="overview">{a.summary}</div>
              {a.member_characters?.length > 0 && (
                <div className="members">涉及人物：{a.member_characters.join("、")}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {chapters.length > 0 && (
        <>
          <h2 className="section-title">章节摘要</h2>
          <div className="card">
            {chapters.map((c, i) => (
              <div key={i} className="chapter-row">
                <span className="ch">{c.chapter}</span> — {c.summary}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function Settings({ cards }) {
  if (cards.length === 0) return <div className="empty">暂无设定卡</div>;
  return (
    <div className="grid cols">
      {cards.map((c, i) => (
        <div key={i} className="card">
          <div className="char-card">
            <div className="name">{c.title}</div>
            <div className="desc">{c.content}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function GraphTab({ id }) {
  const containerRef = useRef(null);
  const [graph, setGraph] = useState(null);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    getGraph(id).then(setGraph).catch((e) => setError(e.message));
  }, [id]);

  // Normalize edges (may be under 'edges' or 'links').
  const edges = useMemo(() => {
    if (!graph) return [];
    return graph.edges || graph.links || [];
  }, [graph]);

  useEffect(() => {
    if (!graph || !containerRef.current) return;
    const nodes = (graph.nodes || []).map((n) => ({
      id: n.id,
      label: n.label,
      shape: n.node_type === "place" ? "box" : "dot",
      size: 12 + Math.min(20, (n.mention_count || 1) * 2),
      color:
        n.node_type === "place"
          ? { background: "#d9d9d9", border: "#b0b0b0" }
          : undefined,
      _raw: n,
    }));
    const visEdges = edges.map((e, i) => ({
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
  }, [graph, edges]);

  if (error) return <div className="error-banner">{error}</div>;
  if (!graph) return <div className="empty"><span className="spinner" /> 加载图谱…</div>;

  return (
    <div>
      <div className="legend">
        {CATEGORY_ORDER.map((cat) => (
          <span key={cat} className="item">
            <span className="swatch" style={{ background: categoryColor(cat) }} />
            {cat}
          </span>
        ))}
      </div>

      <div id="graph" ref={containerRef} />

      {detail?.type === "node" && detail.data && (
        <div className="graph-detail">
          <div className="char-card">
            <span className="name">{detail.data.label}</span>
            {detail.data.role && <span className="role">{detail.data.role}</span>}
          </div>
          {detail.data.description && <div className="desc">{detail.data.description}</div>}
          <div className="k" style={{ marginTop: 8 }}>
            {detail.data.node_type === "place" ? "地点" : "人物"} · 提及 {detail.data.mention_count || 0} 次
          </div>
        </div>
      )}

      {detail?.type === "edge" && detail.data && (
        <div className="graph-detail">
          <div>
            <span className="swatch" style={{ background: categoryColor(detail.data.category), display: "inline-block", width: 12, height: 12, borderRadius: 3, marginRight: 6 }} />
            <strong>{detail.data.category}</strong>
            <span className="k"> · {detail.data.confidence_label}</span>
          </div>
          {detail.data.detail && <div className="desc" style={{ marginTop: 6 }}>{detail.data.detail}</div>}
          {detail.data.evidence && <div className="evidence">「{detail.data.evidence}」</div>}
        </div>
      )}
    </div>
  );
}
