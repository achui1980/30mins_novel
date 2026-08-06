import { useEffect, useState } from "react";
import { getChapterSummary } from "../../api";

export default function ArcsTab({ id, ls, setRight }) {
  const arcs = ls.arcs || [];
  const chapters = ls.chapters || [];
  const [openCh, setOpenCh] = useState(null);
  const [chState, setChState] = useState({});

  async function toggleChapter(i, chapter) {
    if (openCh === i) {
      setOpenCh(null);
      return;
    }
    setOpenCh(i);
    const existing = chState[i];
    if (
      (chapter.summary && chapter.summary.trim()) ||
      (existing && (existing.summary || existing.loading))
    ) {
      return;
    }
    setChState((s) => ({ ...s, [i]: { loading: true } }));
    try {
      const res = await getChapterSummary(id, chapter.chapter);
      setChState((s) => ({ ...s, [i]: { loading: false, summary: res.summary } }));
    } catch (e) {
      setChState((s) => ({ ...s, [i]: { loading: false, error: e.message } }));
    }
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

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <h2 className="font-serif text-lg font-semibold text-ink-900">情节线</h2>
      {arcs.length === 0 ? (
        <div className="mt-4 text-ink-600">未识别到情节线</div>
      ) : (
        <div className="mt-4 space-y-4">
          {arcs.map((a, i) => (
            <div key={i} className="rounded-card border border-ink-300 bg-white p-4">
              <div className="font-serif font-semibold text-ink-900">{a.title}</div>
              <div className="mt-2 text-sm leading-relaxed text-ink-900">{a.summary}</div>
              {a.member_characters?.length > 0 && (
                <div className="mt-2 text-xs text-ink-600">
                  涉及人物：{a.member_characters.join("、")}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {chapters.length > 0 && (
        <>
          <h2 className="mt-8 font-serif text-lg font-semibold text-ink-900">章节摘要</h2>
          <p className="mt-2 text-sm text-ink-600">点击章节，按需生成该章摘要</p>
          <div className="mt-4 divide-y divide-ink-300 rounded-card border border-ink-300 bg-white">
            {chapters.map((c, i) => {
              const open = openCh === i;
              const st = chState[i] || {};
              const body = (c.summary && c.summary.trim()) || st.summary;
              return (
                <div key={i}>
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
                    <div className="px-4 pb-4 text-sm leading-relaxed text-ink-900">
                      {st.loading && (
                        <span>
                          <span className="spinner" /> 生成中…
                        </span>
                      )}
                      {st.error && <span className="text-danger-600">{st.error}</span>}
                      {!st.loading && !st.error && (body || "（暂无摘要）")}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
