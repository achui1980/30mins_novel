import { useCallback, useEffect, useState } from "react";
import { getAskHistory, askQuestion } from "../api";

// Data-fetching core of the "Ask AI about this book" feature: loads past
// Q&A history once, and exposes runAsk(question) to submit a new one. Used
// by the global floating AskAI panel (design spec §2) — extracted out of
// the old AskTab.jsx so the same logic can back a floating panel instead of
// a full tab page.
export function useAskFlow(id) {
  const [history, setHistory] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    getAskHistory(id)
      .then((r) => {
        if (!cancelled) setHistory(r.history || []);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const runAsk = useCallback(
    async (questionText) => {
      const question = (questionText || "").trim();
      if (!question || loading) return null;
      setLoading(true);
      setError("");
      try {
        const res = await askQuestion(id, question);
        const entry = { question, answer: res.answer, cited: res.cited || [] };
        setHistory((h) => [...h, entry]);
        return entry;
      } catch (err) {
        setError(err.message);
        return null;
      } finally {
        setLoading(false);
      }
    },
    [id, loading]
  );

  return { history, loaded, loading, error, runAsk };
}
