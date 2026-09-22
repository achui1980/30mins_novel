import { BookOpen, Clock, Bookmark } from "lucide-react";
import { estimatePanoramaMinutes } from "../../lib/dashboardStats";
import { describeProgress } from "../../lib/readingProgress";

// Hero rewrite: the old version had no visual anchor (24px h1 competing with an
// 18px bold one-liner), used emoji as icons, and buried its only call to action
// in a dotted-underline text link — while the page footer had a solid button
// firing the exact same `onStartReading`. Now: cover block + fluid h1 + SVG
// chips + one primary solid CTA.
export default function HeroSection({ id, pkg, ls, onStartReading }) {
  const chapters = ls.chapters || [];
  const minutes = estimatePanoramaMinutes(pkg, ls);
  const progress = describeProgress(id, chapters);
  const cover = Array.from(pkg.title || "书")[0];

  return (
    <section id="sec-hero" className="scroll-mt-[52px] border-b border-ink-300 pb-8">
      <div className="flex gap-6">
        <div
          aria-hidden="true"
          className="hidden h-[132px] w-[92px] shrink-0 items-center justify-center rounded-[4px] bg-seal-600 font-serif text-4xl text-white shadow-pop sm:flex"
        >
          {cover}
        </div>

        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-2 text-xs tracking-wide text-ink-500">
            <span className="h-px w-6 bg-ink-400" />
            30 分钟读懂一本书
          </p>
          <h1 className="mt-1.5 font-serif text-[clamp(28px,4vw,40px)] font-semibold leading-tight text-ink-900">
            {pkg.title}
          </h1>
          {ls.one_liner && (
            <p className="mt-3 font-serif text-lg leading-relaxed text-ink-800">{ls.one_liner}</p>
          )}
          {ls.story_hook && <p className="mt-2 leading-relaxed text-ink-600">{ls.story_hook}</p>}

          <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-ink-600">
            {chapters.length > 0 && (
              <span className="flex items-center gap-1.5">
                <BookOpen size={14} strokeWidth={1.5} className="text-ink-400" />共{" "}
                <b className="font-medium text-ink-900">{chapters.length}</b> 章
              </span>
            )}
            <span className="flex items-center gap-1.5">
              <Clock size={14} strokeWidth={1.5} className="text-ink-400" />
              全景阅读约 <b className="font-medium text-ink-900">{minutes}</b> 分钟
            </span>
            {progress && (
              <span className="flex items-center gap-1.5">
                <Bookmark size={14} strokeWidth={1.5} className="text-ink-400" />
                读到 {progress.chapterTitle} ·{" "}
                <b className="font-medium text-ink-900">{progress.percent}%</b>
              </span>
            )}
          </div>

          <button
            type="button"
            onClick={onStartReading}
            className="mt-6 inline-flex min-h-[44px] items-center gap-2 rounded-btn bg-seal-600 px-5 text-sm font-medium text-white transition-colors hover:bg-seal-700"
          >
            {progress ? `继续读 ${progress.chapterTitle}` : "开始读原文"}
            <span aria-hidden="true">→</span>
          </button>
        </div>
      </div>
    </section>
  );
}
