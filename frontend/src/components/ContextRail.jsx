import { describeProgress } from "../lib/readingProgress";

// Default content for AppShell's right rail on the reader's 全景/原文 views.
// Before this existed, ReaderPage passed `right={null}` unconditionally, so on
// a 1440px screen the shell was a 140px sidebar plus a centered max-w-3xl
// column with ~266px of dead space on each side. Views that select something
// (graph node, timeline event, arc) replace this via `setRight`.
export default function ContextRail({ id, chapters, activeChapterId, onViewChapter }) {
  const list = chapters || [];
  const progress = describeProgress(id, list);

  return (
    <div className="space-y-5">
      <section>
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-500">阅读进度</h3>
        {progress ? (
          <>
            <p className="mt-1.5 font-serif text-3xl font-semibold leading-none text-ink-900">
              {progress.percent}
              <span className="ml-0.5 text-base font-normal text-ink-500">%</span>
            </p>
            <p className="mt-1 text-xs text-ink-600">读到 {progress.chapterTitle}</p>
            <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-ink-200">
              <div className="h-full rounded-full bg-seal-600" style={{ width: `${progress.percent}%` }} />
            </div>
          </>
        ) : (
          <p className="mt-1.5 text-xs text-ink-600">还没开始读原文</p>
        )}
      </section>

      {list.length > 0 && (
        <section>
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-500">
            章节目录 · 共 {list.length} 章
          </h3>
          <ul className="mt-1.5 space-y-0.5">
            {list.map((c, i) => {
              const active = !!activeChapterId && c.chapter === activeChapterId;
              return (
                <li key={c.chapter}>
                  <button
                    type="button"
                    onClick={() => onViewChapter?.(c.chapter, 0)}
                    aria-current={active ? "true" : undefined}
                    className={`flex w-full items-baseline gap-2 rounded-btn px-2 py-1 text-left text-xs transition-colors ${
                      active
                        ? "bg-white font-medium text-seal-600 shadow-sm2"
                        : "text-ink-600 hover:bg-white hover:text-ink-900"
                    }`}
                  >
                    <span className="w-5 shrink-0 text-right text-[10px] tabular-nums text-ink-400">
                      {i + 1}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{c.title || c.chapter}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
