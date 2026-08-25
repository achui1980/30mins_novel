import SuggestedQuestions from "../SuggestedQuestions";
import SettingsTab from "../tabs/SettingsTab";
import AnchorNav from "./AnchorNav";
import HeroSection from "./HeroSection";
import ArcsPreviewSection from "./ArcsPreviewSection";
import TimelinePreviewSection from "./TimelinePreviewSection";
import CharactersGraphPreviewSection from "./CharactersGraphPreviewSection";

const noop = () => {};

export default function Dashboard({ id, pkg, ls, onAsk, onOpenStack, onViewChapter }) {
  const questions = pkg.suggested_questions || [];

  return (
    <div className="mx-auto max-w-3xl px-8 py-8">
      <AnchorNav />

      <HeroSection id={id} pkg={pkg} ls={ls} onStartReading={() => onOpenStack("raw")} />

      <section className="border-b border-ink-300 py-8">
        <h2 className="font-serif text-lg font-semibold text-ink-900">内容简介</h2>
        {ls.overview ? (
          <p className="mt-3 leading-relaxed text-ink-900">{ls.overview}</p>
        ) : (
          <p className="mt-3 text-ink-600">暂无总览内容。</p>
        )}
      </section>

      <section className="border-b border-ink-300 py-8">
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

      <section id="sec-settings" className="scroll-mt-16 py-8">
        <h2 className="mb-4 font-serif text-lg font-semibold text-ink-900">世界观设定</h2>
        <SettingsTab cards={pkg.setting_cards || []} setRight={noop} />
      </section>

      <div className="mt-4 rounded-card border border-dashed border-ink-300 py-8 text-center">
        <p className="text-ink-900">全景看完了？带着这些人物和线索，去读原文会更有感觉。</p>
        <button
          type="button"
          onClick={() => onOpenStack("raw")}
          className="mt-4 rounded-btn bg-seal-600 px-6 py-3 text-base text-white hover:bg-seal-700"
        >
          开始阅读原文 →
        </button>
      </div>
    </div>
  );
}
