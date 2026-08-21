import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getChapterText } from "../../api";

export default function RawTextTab({ id, ls, jump, setRight }) {
  const chapters = ls?.chapters || [];
  const [chapterState, setChapterState] = useState({}); // chapterId -> { loading, paragraphs }
  const chapterRefs = useRef({});
  const lastHandledNonceRef = useRef(null);

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
    if (!jump || jump.nonce === lastHandledNonceRef.current) return;
    lastHandledNonceRef.current = jump.nonce;
    loadChapter(jump.chapterId);
    setTimeout(() => {
      chapterRefs.current[jump.chapterId]?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  }, [jump, loadChapter]);

  return (
    <div className="mx-auto max-w-2xl">
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
                {p}
              </p>
            ))}
          </div>
        );
      })}
    </div>
  );
}
