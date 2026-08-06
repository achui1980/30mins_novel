import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getWork, graphHtmlUrl } from "../api";
import AppShell from "../components/AppShell";
import OverviewTab from "../components/tabs/OverviewTab";
import CharactersTab from "../components/tabs/CharactersTab";
import StoryTab from "../components/tabs/StoryTab";
import ArcsTab from "../components/tabs/ArcsTab";
import TimelineTab from "../components/tabs/TimelineTab";
import GraphTab from "../components/tabs/GraphTab";
import AskTab from "../components/tabs/AskTab";
import SettingsTab from "../components/tabs/SettingsTab";

const TABS = [
  { key: "overview", label: "总览" },
  { key: "characters", label: "人物" },
  { key: "story", label: "故事正片" },
  { key: "arcs", label: "情节线" },
  { key: "timeline", label: "时间轴" },
  { key: "graph", label: "图谱" },
  { key: "ask", label: "问答" },
  { key: "settings", label: "设置" },
];

export default function ReaderPage() {
  const { id } = useParams();
  const [pkg, setPkg] = useState(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("overview");
  const [askSeed, setAskSeed] = useState(null);
  const [right, setRight] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getWork(id)
      .then((data) => {
        if (!cancelled) setPkg(data);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  function askAbout(question) {
    setAskSeed({ question, nonce: Date.now() });
    setTab("ask");
  }

  if (error) {
    return (
      <AppShell activeWorkId={id} right={null}>
        <div className="mx-auto max-w-3xl px-8 py-10">
          <Link to="/" className="text-sm text-ink-600 hover:text-seal-600">
            ← 返回首页
          </Link>
          <div className="mt-4 rounded-card border border-danger-600 bg-danger-600/10 px-4 py-3 text-sm text-danger-600">
            加载失败：{error}
          </div>
        </div>
      </AppShell>
    );
  }

  if (!pkg) {
    return (
      <AppShell activeWorkId={id} right={null}>
        <div className="flex h-full items-center justify-center">
          <span className="spinner" />
        </div>
      </AppShell>
    );
  }

  const ls = pkg.layered_summary || {};
  const questions = pkg.suggested_questions || [];

  return (
    <AppShell activeWorkId={id} right={right}>
      <div className="mx-auto max-w-4xl px-8 py-8">
        <div className="flex items-start justify-between gap-4">
          <h1 className="font-serif text-2xl text-ink-900">{pkg.title}</h1>
          <a
            href={graphHtmlUrl(id)}
            target="_blank"
            rel="noreferrer"
            className="whitespace-nowrap rounded-btn border border-ink-300 px-3 py-1.5 text-sm text-ink-600 hover:border-seal-600 hover:text-seal-600"
          >
            完整图谱 ↗
          </a>
        </div>

        <div className="mt-6 flex gap-6 border-b border-ink-300">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={
                "border-b-2 px-1 pb-3 text-sm transition-colors " +
                (tab === t.key
                  ? "border-seal-600 font-serif text-seal-600"
                  : "border-transparent text-ink-600 hover:text-ink-900")
              }
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="mt-6">
          {tab === "overview" && (
            <OverviewTab pkg={pkg} ls={ls} onAsk={askAbout} setRight={setRight} />
          )}
          {tab === "characters" && (
            <CharactersTab id={id} pkg={pkg} setRight={setRight} />
          )}
          {tab === "story" && <StoryTab id={id} setRight={setRight} />}
          {tab === "arcs" && <ArcsTab id={id} ls={ls} setRight={setRight} />}
          {tab === "timeline" && <TimelineTab id={id} setRight={setRight} />}
          {tab === "graph" && <GraphTab id={id} setRight={setRight} />}
          {tab === "ask" && (
            <AskTab
              id={id}
              seed={askSeed}
              questions={questions}
              onAsk={askAbout}
              setRight={setRight}
            />
          )}
          {tab === "settings" && (
            <SettingsTab cards={pkg.setting_cards || []} setRight={setRight} />
          )}
        </div>
      </div>
    </AppShell>
  );
}
