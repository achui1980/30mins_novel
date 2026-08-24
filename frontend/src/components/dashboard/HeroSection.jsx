import { estimatePanoramaMinutes } from "../../lib/dashboardStats";
import { describeProgress } from "../../lib/readingProgress";

export default function HeroSection({ id, pkg, ls, onStartReading }) {
  const chapters = ls.chapters || [];
  const minutes = estimatePanoramaMinutes(pkg, ls);
  const progress = describeProgress(id, chapters);

  return (
    <section id="sec-hero" className="scroll-mt-16 border-b border-ink-300 pb-8">
      <p className="text-xs uppercase tracking-wide text-ink-600">30分钟读懂一本书</p>
      <h1 className="mt-1 font-serif text-2xl text-ink-900">{pkg.title}</h1>
      {ls.one_liner && <p className="mt-3 font-serif text-lg font-semibold text-ink-900">{ls.one_liner}</p>}
      {ls.story_hook && <p className="mt-2 text-ink-600">{ls.story_hook}</p>}

      <div className="mt-4 flex flex-wrap gap-4 rounded-card border border-ink-300 bg-paper-100 px-4 py-2 text-xs text-ink-600">
        {chapters.length > 0 && (
          <span>
            📖 共 <b className="text-ink-900">{chapters.length}</b> 章
          </span>
        )}
        <span>
          ⏱ 全景阅读约 <b className="text-ink-900">{minutes}</b> 分钟
        </span>
        {progress && (
          <span>
            🔖 原文已读 <b className="text-ink-900">{progress.percent}%</b>（{progress.chapterTitle}）
          </span>
        )}
      </div>

      <button
        type="button"
        onClick={onStartReading}
        className="mt-4 text-sm text-ink-600 underline decoration-dotted hover:text-seal-600"
      >
        不看全景，直接读原文 →
      </button>
    </section>
  );
}
