import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getChapterText, getGraph } from "../../api";

export default function RawTextTab({ id, ls, jump, setRight }) {
  const chapters = ls?.chapters || [];
  const [chapterState, setChapterState] = useState({}); // chapterId -> { loading, paragraphs }
  const chapterRefs = useRef({});
  const lastHandledNonceRef = useRef(null);
  const progressKey = `novel_kg_reader_progress_${id}`;
  const restoredRef = useRef(null);

  const [fontSize, setFontSize] = useState(() => Number(localStorage.getItem("novel_kg_reader_font_size")) || 16);
  const [theme, setTheme] = useState(() => localStorage.getItem("novel_kg_reader_theme") || "day");

  useEffect(() => { localStorage.setItem("novel_kg_reader_font_size", String(fontSize)); }, [fontSize]);
  useEffect(() => { localStorage.setItem("novel_kg_reader_theme", theme); }, [theme]);

  const FONT_SIZES = [14, 16, 18, 20, 22];
  function stepFontSize(delta) {
    setFontSize((cur) => {
      const idx = FONT_SIZES.indexOf(cur);
      const nextIdx = Math.min(FONT_SIZES.length - 1, Math.max(0, (idx === -1 ? 1 : idx) + delta));
      return FONT_SIZES[nextIdx];
    });
  }

  const [graph, setGraph] = useState(null);
  const [popover, setPopover] = useState(null); // { nodeId, x, y }

  useEffect(() => { getGraph(id).then(setGraph).catch(() => setGraph(null)); }, [id]);

  const nameLookup = useMemo(() => {
    if (!graph?.nodes) return [];
    const entries = [];
    for (const node of graph.nodes) {
      if (node.node_type !== "character" && node.node_type !== "place") continue;
      const names = [node.label, ...(node.aliases || [])].filter(Boolean);
      for (const name of names) entries.push({ name, nodeId: node.id });
    }
    return entries.sort((a, b) => b.name.length - a.name.length); // longest-match-first
  }, [graph]);

  const relationsFor = useCallback(
    (nodeId) => {
      const edges = (graph?.edges || graph?.links || []).filter((e) => e.source === nodeId || e.target === nodeId);
      return edges.map((e) => {
        const otherId = e.source === nodeId ? e.target : e.source;
        const other = graph?.nodes?.find((n) => n.id === otherId);
        return { label: other?.label || otherId, category: e.category };
      });
    },
    [graph]
  );

  function renderWithEntities(text, keyPrefix) {
    if (nameLookup.length === 0) return text;
    const pattern = new RegExp(`(${nameLookup.map((n) => n.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "g");
    const parts = text.split(pattern);
    return parts.map((part, i) => {
      const hit = nameLookup.find((n) => n.name === part);
      if (!hit) return part;
      return (
        <span key={`${keyPrefix}-${i}`} className="entity-link cursor-pointer text-seal-700 underline decoration-dotted" onClick={(evt) => setPopover({ nodeId: hit.nodeId, x: evt.clientX, y: evt.clientY })}>
          {part}
        </span>
      );
    });
  }

  const loadChapter = useCallback(
    async (chapterId) => {
      let shouldFetch = false;
      setChapterState((prev) => {
        if (prev[chapterId]?.loading || prev[chapterId]?.paragraphs) return prev;
        shouldFetch = true;
        return { ...prev, [chapterId]: { loading: true, paragraphs: null } };
      });
      if (!shouldFetch) return;
      try {
        const res = await getChapterText(id, chapterId);
        setChapterState((prev) => ({ ...prev, [chapterId]: { loading: false, paragraphs: res.paragraphs || [] } }));
      } catch (err) {
        setChapterState((prev) => ({ ...prev, [chapterId]: { loading: false, paragraphs: null, error: true } }));
      }
    },
    [id]
  );

  useEffect(() => {
    setRight(
      <div>
        <h3 className="mb-2 text-sm font-semibold text-ink-700">章节目录</h3>
        <ul className="space-y-1">
          {chapters.map((c) => (
            <li key={c.chapter}>
              <button
                type="button"
                onClick={() =>
                  chapterRefs.current[c.chapter]?.scrollIntoView({ behavior: "smooth", block: "start" })
                }
                className="text-sm text-ink-600 hover:text-seal-600 hover:underline"
              >
                {c.title || c.chapter}
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
    return () => setRight(null);
  }, [chapters, setRight]);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const chapterId = entry.target.dataset.chapterId;
            if (chapterId) loadChapter(chapterId);
          }
        }
      },
      { rootMargin: "200px" }
    );
    for (const c of chapters) {
      const el = chapterRefs.current[c.chapter];
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [chapters, loadChapter]);

  useEffect(() => {
    const intersecting = new Map(); // element -> boundingClientRect, persists across callback batches
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            intersecting.set(entry.target, entry.boundingClientRect);
          } else {
            intersecting.delete(entry.target);
          }
        }
        if (intersecting.size === 0) return;
        let topEl = null;
        let topRect = null;
        for (const [el, rect] of intersecting) {
          if (!topRect || rect.top < topRect.top) {
            topEl = el;
            topRect = rect;
          }
        }
        const { chapter, para } = topEl.dataset;
        if (chapter && para !== undefined) {
          localStorage.setItem(progressKey, JSON.stringify({ chapterId: chapter, paragraphIndex: Number(para) }));
        }
      },
      { threshold: 0.1 }
    );
    const paras = document.querySelectorAll("[data-chapter][data-para]");
    for (const el of paras) observer.observe(el);
    return () => observer.disconnect();
  }, [chapterState, progressKey]);

  useEffect(() => {
    if (restoredRef.current === progressKey) return;
    restoredRef.current = progressKey;
    const saved = localStorage.getItem(progressKey);
    if (!saved) return;
    try {
      const { chapterId, paragraphIndex } = JSON.parse(saved);
      loadChapter(chapterId).then(() => {
        setTimeout(() => {
          document.getElementById(`p-${chapterId}-${paragraphIndex}`)?.scrollIntoView({ block: "start" });
        }, 50);
      });
    } catch {
      localStorage.removeItem(progressKey); // clear corrupted saved progress
    }
  }, [progressKey, loadChapter]);

  useEffect(() => {
    if (!jump || jump.nonce === lastHandledNonceRef.current) return;
    lastHandledNonceRef.current = jump.nonce;
    loadChapter(jump.chapterId);
    setTimeout(() => {
      chapterRefs.current[jump.chapterId]?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  }, [jump, loadChapter]);

  const themeClasses = theme === "night" ? "bg-ink-900 text-paper-50" : "bg-white text-ink-900";

  return (
    <>
      <div className={`rounded-md p-4 ${themeClasses}`}>
        <div className="mb-4 flex items-center gap-3 text-sm">
          <button type="button" onClick={() => stepFontSize(-1)} className="rounded border px-2 py-1">A-</button>
          <button type="button" onClick={() => stepFontSize(1)} className="rounded border px-2 py-1">A+</button>
          <button type="button" onClick={() => setTheme((t) => (t === "night" ? "day" : "night"))} className="rounded border px-2 py-1">
            {theme === "night" ? "☀️ 日间" : "🌙 夜间"}
          </button>
        </div>
        <div className="mx-auto max-w-2xl" style={{ fontSize }}>
          {chapters.map((c) => {
            const st = chapterState[c.chapter];
            return (
              <div
                key={c.chapter}
                ref={(el) => {
                  chapterRefs.current[c.chapter] = el;
                }}
                data-chapter-id={c.chapter}
                className="mb-8"
              >
                <h2 className="mb-3 text-lg font-semibold text-ink-800">{c.title || c.chapter}</h2>
                {!st && <p className="text-sm text-ink-400">滚动到此处以加载正文…</p>}
                {st?.loading && <p className="text-sm text-ink-400">加载中…</p>}
                {st?.error && <p className="text-sm text-red-500">加载失败，请重试</p>}
                {st?.paragraphs?.map((p, i) => (
                  <p key={i} id={`p-${c.chapter}-${i}`} data-chapter={c.chapter} data-para={i} className="mb-3 leading-relaxed text-ink-800">
                    {renderWithEntities(p, `${c.chapter}-${i}`)}
                  </p>
                ))}
              </div>
            );
          })}
        </div>
      </div>
      {popover && (
        <EntityPopover
          node={graph?.nodes?.find((n) => n.id === popover.nodeId)}
          relations={relationsFor(popover.nodeId)}
          x={popover.x}
          y={popover.y}
          onClose={() => setPopover(null)}
        />
      )}
    </>
  );
}

function EntityPopover({ node, relations, x, y, onClose }) {
  if (!node) return null;
  return (
    <div className="fixed z-50 max-w-xs rounded-md border border-ink-200 bg-white p-3 shadow-lg" style={{ left: x, top: y }} onMouseLeave={onClose}>
      <p className="font-semibold text-ink-800">{node.label}</p>
      {node.role && <p className="text-xs text-ink-500">{node.role}</p>}
      {node.description && <p className="mt-1 text-sm text-ink-700">{node.description}</p>}
      {relations.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-ink-600">
          {relations.map((r, i) => (<li key={i}>{r.label}（{r.category}）</li>))}
        </ul>
      )}
      <button type="button" onClick={onClose} className="mt-2 text-xs text-ink-400 hover:underline">关闭</button>
    </div>
  );
}
