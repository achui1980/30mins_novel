import { useEffect, useState } from "react";
import SuggestedQuestions from "../SuggestedQuestions";

export default function OverviewTab({ pkg, ls, onAsk, setRight }) {
  const questions = pkg.suggested_questions || [];
  const [q, setQ] = useState("");

  useEffect(() => {
    setRight(
      <div>
        <SuggestedQuestions questions={questions} onAsk={onAsk} />
        <div className="mt-6">
          <h3 className="font-serif text-sm font-semibold text-ink-900">快速提问</h3>
          <form
            className="mt-2 flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (q.trim()) onAsk(q.trim());
              setQ("");
            }}
          >
            <input
              className="rounded-btn border border-ink-300 bg-white px-3 py-2 text-sm"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="输入问题…"
            />
            <button
              type="submit"
              className="rounded-btn bg-seal-600 px-3 py-2 text-sm text-white hover:bg-seal-700"
            >
              提问
            </button>
          </form>
        </div>
      </div>
    );
    return () => setRight(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questions, q]);

  const hasOverview = ls.one_liner || ls.story_hook || ls.overview;

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      {hasOverview ? (
        <div className="rounded-card border border-ink-300 bg-white p-6">
          {ls.one_liner && (
            <p className="font-serif text-xl font-semibold text-ink-900">{ls.one_liner}</p>
          )}
          {ls.story_hook && <p className="mt-3 text-ink-600">{ls.story_hook}</p>}
          {ls.overview && <p className="mt-3 leading-relaxed text-ink-900">{ls.overview}</p>}
        </div>
      ) : (
        <div className="text-ink-600">暂无总览内容。</div>
      )}
    </div>
  );
}
