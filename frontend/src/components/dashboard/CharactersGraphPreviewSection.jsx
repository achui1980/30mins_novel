import { useEffect, useState } from "react";
import { getGraph, getTimeline, graphHtmlUrl } from "../../api";
import { categoryColor } from "../../constants";
import MiniGraphPreview from "./MiniGraphPreview";

export default function CharactersGraphPreviewSection({ id, pkg, onOpenGraph, onViewChapter }) {
  const [graph, setGraph] = useState(null);
  const [events, setEvents] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const mains = pkg.main_characters || [];

  useEffect(() => {
    let cancelled = false;
    getGraph(id)
      .then((g) => {
        if (!cancelled) setGraph(g);
      })
      .catch(() => {
        if (!cancelled) setGraph(null);
      });
    getTimeline(id)
      .then((r) => {
        if (!cancelled) setEvents(r.events || []);
      })
      .catch(() => {
        if (!cancelled) setEvents([]);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  function toggleSelect(charId) {
    setSelectedId((cur) => (cur === charId ? null : charId));
  }

  const selectedNode = selectedId ? graph?.nodes?.find((n) => n.id === selectedId) : null;
  const selectedMain = selectedId ? mains.find((m) => m.id === selectedId) : null;
  const selectedLabel = selectedNode?.label || selectedMain?.label || "";

  const relations = selectedId
    ? (graph?.edges || graph?.links || [])
        .filter((e) => e.source === selectedId || e.target === selectedId)
        .map((e) => {
          const otherId = e.source === selectedId ? e.target : e.source;
          const other = graph?.nodes?.find((n) => n.id === otherId);
          return { label: other?.label || otherId, category: e.category, otherId, sourceLocation: e.source_location };
        })
    : [];

  const appearanceChapters = selectedId
    ? (events || [])
        .filter((ev) => ev.participants?.includes(selectedLabel))
        .reduce((acc, ev) => (acc.includes(ev.chapter_title) ? acc : [...acc, ev.chapter_title]), [])
    : [];

  return (
    <section id="sec-characters" className="scroll-mt-16 border-b border-ink-300 py-8">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-lg font-semibold text-ink-900">人物关系</h2>
        <div className="flex items-center gap-3 text-sm">
          <a
            href={graphHtmlUrl(id)}
            target="_blank"
            rel="noreferrer"
            className="text-ink-600 hover:text-seal-600 hover:underline"
          >
            在新标签页打开 ↗
          </a>
          <button type="button" onClick={onOpenGraph} className="text-ink-600 hover:text-seal-600 hover:underline">
            查看完整图谱→
          </button>
        </div>
      </div>
      {mains.length === 0 ? (
        <p className="mt-4 text-ink-600">未识别到主要人物</p>
      ) : (
        <div className="mt-4 grid grid-cols-2 gap-4">
          {mains.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => toggleSelect(c.id)}
              className={`rounded-card border border-l-4 border-ink-300 bg-white p-4 text-left ${
                selectedId === c.id ? "border-l-seal-600" : "border-l-pine-600"
              }`}
            >
              <div className="font-medium text-ink-900">{c.label}</div>
              {c.description && <div className="mt-1 line-clamp-2 text-sm text-ink-600">{c.description}</div>}
              <div className="mt-2 text-xs text-ink-600">提及 {c.mention_count} 次</div>
            </button>
          ))}
        </div>
      )}
      {selectedId && (
        <div className="mt-4 rounded-card border border-ink-300 bg-paper-50 p-4">
          <h3 className="font-serif text-base font-semibold text-ink-900">{selectedLabel}</h3>
          {selectedNode?.role && <p className="text-sm text-ink-600">{selectedNode.role}</p>}
          {(selectedNode?.description || selectedMain?.description) && (
            <p className="mt-2 text-sm italic text-ink-900">
              {selectedNode?.description || selectedMain?.description}
            </p>
          )}
          {relations.length > 0 && (
            <div className="mt-4">
              <h4 className="text-xs font-semibold uppercase text-ink-600">人物关系</h4>
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
                    {r.sourceLocation && (
                      <button
                        type="button"
                        onClick={() => {
                          const [chapterId, para] = r.sourceLocation.split("#p");
                          onViewChapter?.(chapterId, para !== undefined ? Number(para) : undefined);
                        }}
                        className="ml-2 text-xs text-ink-600 hover:text-seal-600 hover:underline"
                      >
                        查看原文 →
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {appearanceChapters.length > 0 && (
            <div className="mt-4">
              <h4 className="text-xs font-semibold uppercase text-ink-600">出场章节</h4>
              <p className="mt-2 text-sm text-ink-900">{appearanceChapters.join("、")}</p>
            </div>
          )}
        </div>
      )}
      <div className="mt-4 rounded-card border border-dashed border-ink-300 p-3">
        <MiniGraphPreview mainCharacters={mains} graph={graph} />
      </div>
    </section>
  );
}
