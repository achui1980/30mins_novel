import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getChapterText, getGraph } from "../../api";

export default function RawTextTab({ id, ls, jump, setRight, onAskAboutSelection }) {
  const chapters = ls?.chapters || [];
  const [chapterState, setChapterState] = useState({}); // chapterId -> { loading, paragraphs }
  const chapterRefs = useRef({});
  const lastHandledNonceRef = useRef(null);
  const highlightTimeoutRef = useRef(null);
  const progressKey = `novel_kg_reader_progress_${id}`;
  const restoredRef = useRef(null);
  const [selectionButton, setSelectionButton] = useState(null); // { text, chapterTitle, x, y }

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
    let cancelled = false;
    const targetId = jump.paragraphIndex != null ? `p-${jump.chapterId}-${jump.paragraphIndex}` : null;
    const attemptScroll = (retriesLeft) => {
      if (cancelled) return;
      const el = targetId ? document.getElementById(targetId) : chapterRefs.current[jump.chapterId];
      if (!el && targetId && retriesLeft > 0) {
        setTimeout(() => attemptScroll(retriesLeft - 1), 100);
        return;
      }
      el?.scrollIntoView({ behavior: "smooth", block: "start" });
      if (targetId && el) {
        if (highlightTimeoutRef.current) {
          clearTimeout(highlightTimeoutRef.current.timeoutId);
          if (highlightTimeoutRef.current.el !== el) {
            // A different paragraph was mid-highlight; remove its highlight
            // immediately instead of leaving it stuck once its timer is cancelled.
            highlightTimeoutRef.current.el.classList.remove("bg-amber-100");
          }
        }
        el.classList.add("bg-amber-100");
        highlightTimeoutRef.current = {
          el,
          timeoutId: setTimeout(() => el.classList.remove("bg-amber-100"), 1200),
        };
      }
    };
    loadChapter(jump.chapterId).then(() => {
      // Wait for React to commit + paint the post-load DOM before looking up the
      // target element; fall back to a few bounded retries in case unrelated
      // IntersectionObserver-driven re-renders delay the commit further.
      requestAnimationFrame(() => requestAnimationFrame(() => attemptScroll(8)));
    });
    return () => {
      cancelled = true;
    };
  }, [jump, loadChapter]);

  useEffect(() => {
    function handleMouseUp(event) {
      const sel = window.getSelection();
      const text = sel?.toString().trim();
      // Suppress the ask-button only for a genuine click on an entity-link (no
      // drag): a plain click collapses/clears any selection by the time mouseup
      // fires, so `text` is empty here and EntityPopover's own onClick owns the
      // UI for this interaction instead (a lingering text selection from before
      // the click could otherwise leave both floating widgets on screen at
      // once). A drag-selection that merely happens to end over an
      // entity-highlighted span still produces a non-empty `text` and must
      // still show the ask button — do not suppress it just because the
      // release point is inside .entity-link.
      if (!text) {
        setSelectionButton(null);
        return;
      }
      const anchorNode = sel.anchorNode;
      // anchorNode can be a Text node (normal case) or an Element (e.g. selection
      // anchored at a paragraph boundary via double/triple-click) — resolve both
      // to the element that should carry data-chapter before walking up.
      const anchorEl = anchorNode?.nodeType === Node.TEXT_NODE ? anchorNode.parentElement : anchorNode;
      const paraEl = anchorEl?.closest("[data-chapter]");
      const chapterId = paraEl?.dataset.chapter;
      const chapterTitle = chapters.find((c) => c.chapter === chapterId)?.title || chapterId || "";
      const range = sel.getRangeAt(0);
      const rect = range.getBoundingClientRect();
      setSelectionButton({ text, chapterTitle, x: rect.right, y: rect.bottom });
    }
    function handleSelectionChange() {
      // Clears the button for any deselection path other than mouseup (e.g.
      // programmatic removeAllRanges(), focus changes) so it never desyncs from
      // the real DOM selection. mouseup remains the only path that *shows* the
      // button, since it gives a clean final range once dragging has ended.
      const text = window.getSelection()?.toString().trim();
      if (!text) setSelectionButton(null);
    }
    function handleScroll() {
      // The reader's actual scroll container is an ancestor <main
      // className="overflow-y-auto">, not window — listen on the capture phase
      // so scrolling that inner container is also caught. Dismiss rather than
      // reposition, since the button would otherwise float detached from the
      // (now-moved) selected text.
      setSelectionButton(null);
    }
    document.addEventListener("mouseup", handleMouseUp);
    document.addEventListener("selectionchange", handleSelectionChange);
    document.addEventListener("scroll", handleScroll, true);
    return () => {
      document.removeEventListener("mouseup", handleMouseUp);
      document.removeEventListener("selectionchange", handleSelectionChange);
      document.removeEventListener("scroll", handleScroll, true);
    };
  }, [chapters]);

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
      {selectionButton && (
        <button
          type="button"
          className="fixed z-50 rounded bg-seal-600 px-2 py-1 text-xs text-white shadow"
          style={{ left: selectionButton.x, top: selectionButton.y }}
          onClick={() => {
            const question = selectionButton.chapterTitle
              ? `关于这段内容：「${selectionButton.text}」（出自${selectionButton.chapterTitle}），我想问：`
              : `关于这段内容：「${selectionButton.text}」，我想问：`;
            onAskAboutSelection?.(question);
            setSelectionButton(null);
          }}
        >
          就这段问AI
        </button>
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
