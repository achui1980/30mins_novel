import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getWork } from "../api";
import AppShell from "../components/AppShell";
import AskAI from "../components/AskAI";
import SettingsOverlay from "../components/SettingsOverlay";
import ContextRail from "../components/ContextRail";
import Dashboard from "../components/dashboard/Dashboard";
import RawTextTab from "../components/tabs/RawTextTab";
import GraphTab from "../components/tabs/GraphTab";
import ArcsTab from "../components/tabs/ArcsTab";
import TimelineTab from "../components/tabs/TimelineTab";
import StoryTab from "../components/tabs/StoryTab";
import { READER_VIEWS, DEFAULT_VIEW, isReaderView, readerViewTitle } from "../components/readerViews";
import { getReadingProgress } from "../lib/readingProgress";
import { useReaderPrefs } from "../hooks/useReaderPrefs";
import { Settings } from "lucide-react";

// The five deep-dive views used to be `fixed inset-0 z-40` overlays with local
// `right` state (see the deleted components/stacks/*). They are now routed
// views (`/works/:id/:view`) rendered inside AppShell, and `right` lives here
// so the context rail is shared by every view and never collapses — which is
// what removes the ~266px of dead space on each side of the old layout.
export default function ReaderPage() {
  const { id, view: viewParam } = useParams();
  const navigate = useNavigate();
  const view = isReaderView(viewParam) ? viewParam : DEFAULT_VIEW;

  const [pkg, setPkg] = useState(null);
  const [error, setError] = useState(null);

  const [right, setRight] = useState(null);
  const [jump, setJump] = useState(null);

  const [askOpen, setAskOpen] = useState(false);
  const [askSeed, setAskSeed] = useState(null);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const prefs = useReaderPrefs();

  useEffect(() => {
    let cancelled = false;
    getWork(id)
      .then((r) => {
        if (!cancelled) setPkg(r);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Each view owns the rail; drop the previous view's selection on switch.
  useEffect(() => {
    setRight(null);
  }, [view]);

  function goView(target, params) {
    setJump(params || null);
    navigate(target === DEFAULT_VIEW ? `/works/${id}` : `/works/${id}/${target}`);
  }

  function askAbout(question) {
    setAskSeed({ question, nonce: Date.now() });
  }

  function askAboutSelection(question) {
    setAskSeed({ question, autoSubmit: false, nonce: Date.now() });
  }

  function viewChapter(chapterId, paragraphIndex) {
    goView("raw", { chapterId, paragraphIndex, nonce: Date.now() });
  }

  if (error) {
    return (
      <AppShell activeWorkId={id}>
        <div className="p-8 text-danger-600">{error}</div>
      </AppShell>
    );
  }

  if (!pkg) {
    return (
      <AppShell activeWorkId={id}>
        <div className="p-8 text-ink-600">加载中…</div>
      </AppShell>
    );
  }

  const ls = pkg.layered_summary || {};
  const chapters = ls.chapters || [];
  const saved = getReadingProgress(id);

  // Always non-null so selecting a node/event never shifts the layout.
  const rightNode =
    right ||
    (view === "overview" || view === "raw" ? (
      <ContextRail
        id={id}
        chapters={chapters}
        activeChapterId={saved?.chapterId}
        onViewChapter={viewChapter}
      />
    ) : (
      <p className="text-xs leading-relaxed text-ink-500">
        点击{view === "graph" ? "人物或关系" : view === "timeline" ? "时间轴上的事件" : "左侧条目"}
        ，这里会显示详情。
      </p>
    ));

  return (
    <>
      <AppShell
        activeWorkId={id}
        title={pkg.title}
        views={READER_VIEWS}
        activeView={view}
        onView={goView}
        right={rightNode}
      >
        {view !== "overview" && (
          <header className="sticky top-0 z-10 border-b border-ink-300 bg-paper-50/95 px-6 py-3 backdrop-blur">
            <h1 className="font-serif text-base font-semibold">{readerViewTitle(view)}</h1>
          </header>
        )}

        {view === "overview" && (
          <Dashboard
            id={id}
            pkg={pkg}
            ls={ls}
            onAsk={askAbout}
            onOpenStack={goView}
            onViewChapter={viewChapter}
          />
        )}

        {view === "graph" && (
          <div className="px-6 py-4">
            <GraphTab id={id} setRight={setRight} onViewChapter={viewChapter} />
          </div>
        )}

        {view === "arcs" && (
          <div className="px-6 py-4">
            <ArcsTab id={id} ls={ls} setRight={setRight} />
          </div>
        )}

        {view === "timeline" && (
          <div className="px-6 py-4">
            <TimelineTab id={id} setRight={setRight} onViewChapter={viewChapter} />
          </div>
        )}

        {view === "story" && (
          <div className="px-6 py-4">
            <StoryTab id={id} setRight={setRight} />
          </div>
        )}

        {view === "raw" && (
          <div className="mx-auto max-w-[68ch] px-6 py-6">
            <RawTextTab
              id={id}
              ls={ls}
              jump={jump}
              setRight={setRight}
              onAskAboutSelection={askAboutSelection}
              fontSize={prefs.fontSize}
              theme={prefs.theme}
              onStepFontSize={prefs.stepFontSize}
              onToggleTheme={prefs.toggleTheme}
            />
          </div>
        )}
      </AppShell>

      <AskAI id={id} open={askOpen} onOpenChange={setAskOpen} seed={askSeed} />
      <SettingsOverlay open={settingsOpen} onClose={() => setSettingsOpen(false)} prefs={prefs} />
      <button
        type="button"
        onClick={() => setSettingsOpen(true)}
        aria-label="设置"
        className="fixed right-4 top-4 z-50 rounded-full border border-ink-300 bg-white p-2 shadow-sm2 hover:border-seal-600"
      >
        <Settings size={18} strokeWidth={1.5} className="text-ink-600" />
      </button>
    </>
  );
}
