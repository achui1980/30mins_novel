import { useEffect, useRef, useState } from "react";
import { getChapterText } from "../../api";

export default function RawTextTab({ id, ls, jump, setRight }) {
  const chapters = ls.chapters || [];
  const [openCh, setOpenCh] = useState(null);
  const [chState, setChState] = useState({});
  const chapterRefs = useRef({});
  const lastHandledNonceRef = useRef(null);

  async function loadChapter(i, chapter) {
    const existing = chState[i];
    if (existing && (existing.text || existing.loading)) {
      return;
    }
    setChState((s) => ({ ...s, [i]: { loading: true } }));
    try {
      const res = await getChapterText(id, chapter.chapter);
      setChState((s) => ({ ...s, [i]: { loading: false, text: res.text } }));
    } catch (e) {
      setChState((s) => ({ ...s, [i]: { loading: false, error: e.message } }));
    }
  }

  function toggleChapter(i, chapter) {
    if (openCh === i) {
      setOpenCh(null);
      return;
    }
    setOpenCh(i);
    loadChapter(i, chapter);
  }

  useEffect(() => {
    if (chapters.length === 0) {
      setRight(null);
      return () => setRight(null);
    }
    setRight(
      <div>
        <h3 className="font-serif text-sm font-semibold text-ink-900">章节目录</h3>
        <ul className="mt-3 space-y-1">
          {chapters.map((c, i) => (
            <li key={i}>
              <button
                type="button"
                onClick={() => toggleChapter(i, c)}
                className={`block w-full truncate rounded px-2 py-1 text-left text-sm ${
                  openCh === i
                    ? "border-l-2 border-seal-600 bg-seal-100/40 text-seal-600"
                    : "text-ink-900 hover:bg-paper-50"
                }`}
              >
                {c.title || c.chapter}
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
    return () => setRight(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapters, openCh]);

  useEffect(() => {
    if (!jump || jump.nonce === lastHandledNonceRef.current) return;
    const idx = chapters.findIndex((c) => c.chapter === jump.chapterId);
    if (idx === -1) return;
    lastHandledNonceRef.current = jump.nonce;
    setOpenCh(idx);
    loadChapter(idx, chapters[idx]);
    setTimeout(() => {
      chapterRefs.current[idx]?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jump, chapters]);

  if (chapters.length === 0) {
    return <div className="mx-auto max-w-3xl px-8 py-10 text-ink-600">暂无章节原文</div>;
  }

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <h2 className="font-serif text-lg font-semibold text-ink-900">原文</h2>
      <p className="mt-2 text-sm text-ink-600">点击章节展开原文</p>
      <div className="mt-4 divide-y divide-ink-300 rounded-card border border-ink-300 bg-white">
        {chapters.map((c, i) => {
          const open = openCh === i;
          const st = chState[i] || {};
          return (
            <div key={i} ref={(el) => (chapterRefs.current[i] = el)}>
              <button
                type="button"
                onClick={() => toggleChapter(i, c)}
                className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-ink-900"
              >
                <span>{c.title || c.chapter}</span>
                <span className={open ? "text-seal-600" : "text-ink-600"}>
                  {open ? "▾" : "▸"}
                </span>
              </button>
              {open && (
                <div className="whitespace-pre-wrap px-4 pb-4 text-sm leading-relaxed text-ink-900">
                  {st.loading && (
                    <span>
                      <span className="spinner" /> 加载中…
                    </span>
                  )}
                  {st.error && <span className="text-danger-600">{st.error}</span>}
                  {!st.loading && !st.error && (st.text || "（暂无原文）")}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
