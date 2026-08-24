import { useEffect, useState } from "react";
import { getGraph, graphHtmlUrl } from "../../api";
import MiniGraphPreview from "./MiniGraphPreview";

export default function CharactersGraphPreviewSection({ id, pkg, onOpenGraph }) {
  const [graph, setGraph] = useState(null);
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
    return () => {
      cancelled = true;
    };
  }, [id]);

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
            <div key={c.id} className="rounded-card border border-ink-300 bg-white p-4">
              <div className="font-medium text-ink-900">{c.label}</div>
              {c.description && <div className="mt-1 line-clamp-2 text-sm text-ink-600">{c.description}</div>}
              <div className="mt-2 text-xs text-ink-600">提及 {c.mention_count} 次</div>
            </div>
          ))}
        </div>
      )}
      <div className="mt-4 rounded-card border border-dashed border-ink-300 p-3">
        <MiniGraphPreview mainCharacters={mains} graph={graph} />
      </div>
    </section>
  );
}
