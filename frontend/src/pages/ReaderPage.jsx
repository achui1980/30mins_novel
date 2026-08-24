import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getWork } from "../api";
import AppShell from "../components/AppShell";
import AskAI from "../components/AskAI";
import SettingsOverlay from "../components/SettingsOverlay";
import Dashboard from "../components/dashboard/Dashboard";
import RawTextStack from "../components/stacks/RawTextStack";
import GraphStack from "../components/stacks/GraphStack";
import ArcsStack from "../components/stacks/ArcsStack";
import TimelineStack from "../components/stacks/TimelineStack";
import StoryStack from "../components/stacks/StoryStack";
import { useReaderPrefs } from "../hooks/useReaderPrefs";
import { Settings } from "lucide-react";

export default function ReaderPage() {
  const { id } = useParams();
  const [pkg, setPkg] = useState(null);
  const [error, setError] = useState(null);

  const [activeStack, setActiveStack] = useState(null); // null | raw | graph | arcs | timeline | story
  const [stackParams, setStackParams] = useState(null);

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

  function openStack(target, params) {
    setStackParams(params || null);
    setActiveStack(target);
  }

  function closeStack() {
    setActiveStack(null);
  }

  function askAbout(question) {
    setAskSeed({ question, nonce: Date.now() });
  }

  function askAboutSelection(question) {
    setAskSeed({ question, autoSubmit: false, nonce: Date.now() });
  }

  function viewChapter(chapterId, paragraphIndex) {
    openStack("raw", { chapterId, paragraphIndex, nonce: Date.now() });
  }

  if (error) {
    return (
      <AppShell activeWorkId={id} right={null}>
        <div className="p-8 text-danger-600">{error}</div>
      </AppShell>
    );
  }

  if (!pkg) {
    return (
      <AppShell activeWorkId={id} right={null}>
        <div className="p-8 text-ink-600">加载中…</div>
      </AppShell>
    );
  }

  const ls = pkg.layered_summary || {};

  return (
    <>
      <AppShell activeWorkId={id} right={null}>
        <Dashboard id={id} pkg={pkg} ls={ls} onAsk={askAbout} onOpenStack={openStack} />
      </AppShell>

      {activeStack === "raw" && (
        <RawTextStack
          id={id}
          ls={ls}
          jump={stackParams}
          onBack={closeStack}
          onAskAboutSelection={askAboutSelection}
          prefs={prefs}
        />
      )}
      {activeStack === "graph" && <GraphStack id={id} onBack={closeStack} onViewChapter={viewChapter} />}
      {activeStack === "arcs" && <ArcsStack id={id} ls={ls} onBack={closeStack} />}
      {activeStack === "timeline" && <TimelineStack id={id} onBack={closeStack} onViewChapter={viewChapter} />}
      {activeStack === "story" && <StoryStack id={id} onBack={closeStack} />}

      <AskAI id={id} open={askOpen} onOpenChange={setAskOpen} seed={askSeed} />
      <SettingsOverlay open={settingsOpen} onClose={() => setSettingsOpen(false)} prefs={prefs} />
      <button
        type="button"
        onClick={() => setSettingsOpen(true)}
        aria-label="设置"
        className="fixed top-4 right-4 z-50 rounded-full border border-ink-300 bg-white p-2 shadow-sm2 hover:border-seal-600"
      >
        <Settings size={18} strokeWidth={1.5} className="text-ink-600" />
      </button>
    </>
  );
}
