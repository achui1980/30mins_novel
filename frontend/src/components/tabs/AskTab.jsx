import { useEffect, useRef, useState } from "react";
import { getAskHistory, askQuestion } from "../../api";
import SuggestedQuestions from "../SuggestedQuestions";

export default function AskTab({ id, seed, questions, onAsk, setRight }) {
  const [history, setHistory] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  // Tracks the most recently *handled* seed nonce so the seed effect below
  // only calls runAsk once per distinct click, even though it re-runs on
  // every render where `loaded` or `seed` changes.
  const lastHandledNonceRef = useRef(null);

  useEffect(() => {
    setRight(<SuggestedQuestions questions={questions} onAsk={onAsk} />);
    return () => setRight(null);
  }, [questions, onAsk, setRight]);

  useEffect(() => {
    getAskHistory(id)
      .then((r) => setHistory(r.history || []))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, [id]);

  async function runAsk(questionText) {
    const question = (questionText || "").trim();
    if (!question || loading) return;
    setLoading(true);
    setError("");
    try {
      const res = await askQuestion(id, question);
      const entry = { question, answer: res.answer, cited: res.cited || [] };
      setHistory((h) => [...h, entry]);
      setQ("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  // A "seed" question (design §4.2c: click a suggested question -> jump here
  // and auto-submit). `nonce` changes on every click so re-clicking the same
  // question re-submits it instead of being a no-op. Gated on `loaded` so
  // this can only fire after the mount-time history load above has settled.
  useEffect(() => {
    if (loaded && seed && seed.nonce !== lastHandledNonceRef.current) {
      lastHandledNonceRef.current = seed.nonce;
      runAsk(seed.question);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed, loaded]);

  async function submit(e) {
    e.preventDefault();
    await runAsk(q);
  }

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="rounded-card border border-ink-300 bg-white p-6">
        <p className="text-sm text-ink-600">
          基于这本书的知识图谱与情节信息回答你的问题（仅依据已分析内容，不会凭空编造）。
        </p>
        <form onSubmit={submit} className="mt-4 flex gap-2">
          <input
            className="flex-1 rounded-btn border border-ink-300 px-3 py-2 text-sm"
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="例如：主角和反派是什么关系？"
            disabled={loading}
          />
          <button
            type="submit"
            className="rounded-btn bg-seal-600 px-4 py-2 text-sm text-white hover:bg-seal-700 disabled:opacity-50"
            disabled={loading || !q.trim()}
          >
            {loading ? "思考中…" : "提问"}
          </button>
        </form>
        {error && <div className="mt-3 text-sm text-danger-600">{error}</div>}
      </div>

      {loaded && history.length === 0 && !loading && (
        <div className="mt-6 text-ink-600">还没有问答记录，试着问一个问题吧。</div>
      )}

      <div className="mt-6 space-y-4">
        {[...history].reverse().map((item, i) => (
          <div key={i} className="rounded-card border border-ink-300 bg-white p-4">
            <p className="font-medium text-ink-900">Q：{item.question}</p>
            <p className="mt-2 whitespace-pre-wrap text-sm text-ink-900">{item.answer}</p>
            {item.cited?.length > 0 && (
              <p className="mt-2 text-xs text-ink-600">涉及：{item.cited.join("、")}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
