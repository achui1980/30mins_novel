import { useEffect, useRef, useState } from "react";
import { MessageCircle, X } from "lucide-react";
import { useAskFlow } from "../hooks/useAskFlow";

// Global floating "Ask AI" entry point (design spec §2): replaces the old
// dedicated 问答 tab. Mounted once at the ReaderPage level so it floats on
// top of both the Dashboard and every full-screen stack sub-page.
export default function AskAI({ id, open, onOpenChange, seed }) {
  const { history, loaded, loading, error, runAsk } = useAskFlow(id);
  const [q, setQ] = useState("");
  const lastHandledNonceRef = useRef(null);

  useEffect(() => {
    if (!seed || seed.nonce === lastHandledNonceRef.current) return;
    lastHandledNonceRef.current = seed.nonce;
    onOpenChange(true);
    if (seed.autoSubmit === false) {
      setQ(seed.question);
    } else {
      runAsk(seed.question);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed]);

  async function submit(e) {
    e.preventDefault();
    if (!q.trim()) return;
    await runAsk(q);
    setQ("");
  }

  return (
    <>
      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2 rounded-full bg-ink-900 px-4 py-3 text-sm text-white shadow-pop hover:bg-ink-900/90"
      >
        <MessageCircle size={16} strokeWidth={1.5} />
        问AI
      </button>
      {open && (
        <div className="fixed bottom-24 right-6 z-50 flex max-h-[70vh] w-[340px] flex-col rounded-card border border-ink-300 bg-white shadow-pop">
          <div className="flex items-center justify-between border-b border-ink-300 px-4 py-3">
            <h3 className="font-serif text-sm font-semibold text-ink-900">问AI</h3>
            <button type="button" onClick={() => onOpenChange(false)} aria-label="关闭">
              <X size={16} strokeWidth={1.5} className="text-ink-600" />
            </button>
          </div>
          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {loaded && history.length === 0 && !loading && (
              <p className="text-sm text-ink-600">还没有问答记录，试着问一个问题吧。</p>
            )}
            {[...history].reverse().map((item, i) => (
              <div key={i} className="rounded-card border border-ink-300 bg-paper-50 p-3">
                <p className="text-sm font-medium text-ink-900">Q：{item.question}</p>
                <p className="mt-1 whitespace-pre-wrap text-sm text-ink-900">{item.answer}</p>
              </div>
            ))}
          </div>
          {error && <div className="px-4 pb-2 text-sm text-danger-600">{error}</div>}
          <form onSubmit={submit} className="flex gap-2 border-t border-ink-300 p-3">
            <input
              className="flex-1 rounded-btn border border-ink-300 px-3 py-2 text-sm"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="输入问题…"
              disabled={loading}
            />
            <button
              type="submit"
              className="rounded-btn bg-seal-600 px-3 py-2 text-sm text-white hover:bg-seal-700 disabled:opacity-50"
              disabled={loading || !q.trim()}
            >
              {loading ? "…" : "问"}
            </button>
          </form>
        </div>
      )}
    </>
  );
}
