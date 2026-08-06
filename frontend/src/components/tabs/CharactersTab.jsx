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
