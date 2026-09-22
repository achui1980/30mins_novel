import SuggestedQuestions from "../SuggestedQuestions";
import SettingsTab from "../tabs/SettingsTab";
import AnchorNav from "./AnchorNav";
import HeroSection from "./HeroSection";
import ArcsPreviewSection from "./ArcsPreviewSection";
import TimelinePreviewSection from "./TimelinePreviewSection";
import CharactersGraphPreviewSection from "./CharactersGraphPreviewSection";

const noop = () => {};

const BEAT_TONES = ["bg-pine-600", "bg-amber-600", "bg-seal-600", "bg-ink-700"];

// The summarizer emits `overview` as one long string with inline 【起因】【发展】
// 【高潮】【结局】 markers, which used to render as a single unbroken wall of
// text. Split it back into beats so the section can be laid out as cards; fall
// back to the raw paragraph when the markers are absent.
function splitOverview(text) {
  if (!text) return [];
  const marks = [...text.matchAll(/【([^】]{1,8})】/g)];
  if (marks.length < 2) return [];
  return marks
    .map((m, i) => ({
      label: m[1],
      body: text
        .slice(m.index + m[0].length, i + 1 < marks.length ? marks[i + 1].index : undefined)
        .trim(),
    }))
    .filter((b) => b.body);
}

// No 【】 markers (the common case for LLM output): the overview arrives as one
// 10-line block. Break it into 3-sentence paragraphs so it reads as prose rather
// than a wall of text. No headings are invented — only whitespace is added.
function splitSentences(text, per = 3) {
  if (!text) return [];
  const sentences = text.match(/[^。！？]*[。！？]+|[^。！？]+$/g) || [text];
  const out = [];
  for (let i = 0; i < sentences.length; i += per) {
    out.push(sentences.slice(i, i + per).join("").trim());
  }
  return out.filter(Boolean);
}

export default function Dashboard({ id, pkg, ls, onAsk, onOpenStack, onViewChapter }) {
  const questions = pkg.suggested_questions || [];
  const beats = splitOverview(ls.overview);

  return (
    <div className="mx-auto max-w-3xl px-6 py-8 md:px-8">
      <AnchorNav />

      <HeroSection id={id} pkg={pkg} ls={ls} onStartReading={() => onOpenStack("raw")} />

      <section id="sec-overview" className="scroll-mt-[52px] border-b border-ink-300 py-8">
        <h2 className="font-serif text-lg font-semibold text-ink-900">故事梗概</h2>
        {beats.length > 0 ? (
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {beats.map((b, i) => (
              <div key={b.label} className="rounded-card border border-ink-200 bg-paper-100 p-4">
                <h3 className="flex items-center gap-2 text-sm font-medium text-ink-900">
                  <span
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] text-white ${BEAT_TONES[i % BEAT_TONES.length]}`}
                  >
                    {i + 1}
                  </span>
                  {b.label}
                </h3>
                <p className="mt-2 text-[13px] leading-relaxed text-ink-700">{b.body}</p>
              </div>
            ))}
          </div>
        ) : ls.overview ? (
          <div className="mt-3 space-y-3 leading-relaxed text-ink-800">
            {splitSentences(ls.overview).map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-ink-600">暂无总览内容。</p>
        )}
      </section>

      <section id="sec-questions" className="scroll-mt-[52px] border-b border-ink-300 py-8">
        <SuggestedQuestions questions={questions} onAsk={onAsk} />
      </section>

      <CharactersGraphPreviewSection
        id={id}
        pkg={pkg}
        onOpenGraph={() => onOpenStack("graph")}
        onViewChapter={onViewChapter}
      />

      <ArcsPreviewSection
        ls={ls}
        onOpenArcs={() => onOpenStack("arcs")}
        onOpenStory={() => onOpenStack("story")}
      />

      <TimelinePreviewSection id={id} onOpenTimeline={() => onOpenStack("timeline")} />

      <section id="sec-settings" className="scroll-mt-[52px] py-8">
        <h2 className="mb-4 font-serif text-lg font-semibold text-ink-900">世界观设定</h2>
        <SettingsTab cards={pkg.setting_cards || []} setRight={noop} />
      </section>

      <div className="py-8 text-center">
        <p className="text-sm text-ink-600">全景看完了？带着这些人物和线索，去读原文会更有感觉。</p>
        <button
          type="button"
          onClick={() => onOpenStack("raw")}
          className="mt-2 text-sm text-seal-600 underline decoration-ink-300 underline-offset-4 hover:decoration-seal-600"
        >
          去读原文 →
        </button>
      </div>
    </div>
  );
}
