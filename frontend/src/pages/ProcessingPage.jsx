import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { getStatus, reanalyzeWork } from "../api";
import { PHASE_LABELS, PHASE_ORDER } from "../constants";
import AppShell from "../components/AppShell";

const PHASE_EXPLAIN = {
  queued: "任务已提交，等待处理开始。",
  parsing: "正在解析文本文件，切分章节与段落。",
  extracting: "正在从文本中抽取人物、地点、事件与关系。",
  building: "正在基于抽取结果构建知识图谱。",
  summarizing: "正在生成分层摘要与人物卡片。",
  done: "处理完成。",
  failed: "处理过程中出现错误。",
};

export default function ProcessingPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [retryMsg, setRetryMsg] = useState("");
  const [retryPending, setRetryPending] = useState(false);
  // Bumped after a successful reanalyze to restart the poll chain below.
  // The chain is self-rescheduling and deliberately stops when phase ===
  // "failed", so by the time the failure card is on screen there is no
  // pending timer left to pick up the new run — only re-running the effect
  // starts a fresh chain.
  const [retryNonce, setRetryNonce] = useState(0);
  // One shared timer ref is sufficient because at most one poll chain is ever
  // alive: every teardown both poisons its own closure's `cancelled` flag and
  // clears the pending timer, and React flushes all cleanups before all
  // creates. A future change that lets polling continue past "failed", or that
  // adds a second poller, would silently double-book `timer.current` and leak a
  // timer — and no test would catch it.
  const timer = useRef(null);
  // The live work id, for `onRetry`'s identity guard. A plain `const myId = id`
  // comparison cannot work: `onRetry` closes over the very same `id` binding it
  // would compare against, so the check is structurally always false. This ref
  // is the only thing in the component that sees the *current* id from inside a
  // stale closure. Assigned during render on purpose — it is idempotent and
  // derived straight from the route param, so a repeated render writes the same
  // value; doing it in an effect instead would leave a window in which a POST
  // resolves before the effect has caught up.
  const liveId = useRef(id);
  liveId.current = id;

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const s = await getStatus(id);
        if (cancelled) return;
        setStatus(s);
        setError("");
        if (s.phase === "done") {
          navigate(`/works/${id}`, { replace: true });
          return;
        }
        if (s.phase === "failed") return;
        timer.current = setTimeout(poll, 2000);
      } catch (e) {
        if (cancelled) return;
        setError(e.message || "网络错误");
        timer.current = setTimeout(poll, 3000);
      }
    }
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer.current);
    };
  }, [id, navigate, retryNonce]);

  async function onRetry() {
    if (retryPending) return;
    // Identity guard. The effect's `cancelled` flag is declared inside the
    // effect body, so it does not cover anything out here: a POST for work A
    // that resolves after the route has switched to work B would otherwise
    // blank B's status and tear down / restart B's poll chain.
    const myId = id;
    setRetryPending(true);
    setRetryMsg("正在提交…");
    try {
      await reanalyzeWork(id);
      if (liveId.current !== myId) return;
      setRetryMsg("");
      // Clearing status swaps the failure card for the progress card;
      // bumping the nonce is what actually revives polling.
      setStatus(null);
      setRetryNonce((n) => n + 1);
    } catch (e) {
      if (liveId.current !== myId) return;
      setRetryMsg(e.message || "重新分析失败");
    } finally {
      setRetryPending(false);
    }
  }

  const phase = status?.phase || "queued";
  const failed = phase === "failed";
  const currentIdx = PHASE_ORDER.indexOf(phase);
  let pct = currentIdx >= 0 ? (currentIdx / (PHASE_ORDER.length - 1)) * 100 : 0;
  if (phase === "extracting" && typeof status?.progress === "number") {
    const span = 100 / (PHASE_ORDER.length - 1);
    pct = (currentIdx / (PHASE_ORDER.length - 1)) * 100 + status.progress * span;
  }

  const right = (
    <div className="space-y-4 text-xs">
      <h2 className="font-serif text-sm font-semibold text-ink-900">当前阶段说明</h2>
      <p className="text-ink-600">{PHASE_EXPLAIN[phase]}</p>
      <div className="space-y-1 border-t border-ink-300 pt-2">
        <h3 className="font-medium text-ink-900">进度日志</h3>
        {PHASE_ORDER.filter((p) => p !== "queued").map((p, i) => (
          <div
            key={p}
            className={`flex items-center gap-1.5 ${i <= currentIdx ? "text-pine-600" : "text-ink-600"}`}
          >
            <span>{i < currentIdx ? "✓" : i === currentIdx ? "●" : "○"}</span>
            <span>{PHASE_LABELS[p]}</span>
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <AppShell activeWorkId={id} right={failed ? null : right}>
      <div className="mx-auto max-w-2xl px-8 py-12">
        <h1 className="font-serif text-2xl font-semibold text-ink-900">{status?.title || "处理中"}</h1>

        {failed ? (
          <div className="mt-6 rounded-card border border-ink-300 bg-white p-6">
            <div className="rounded-card border border-danger-600/40 bg-danger-600/5 px-4 py-2 text-sm text-danger-600">
              处理失败：{status?.error || status?.message || "未知错误"}
            </div>
            <div className="mt-4 flex items-center gap-3">
              <button
                type="button"
                onClick={onRetry}
                disabled={retryPending}
                aria-busy={retryPending}
                className="rounded-btn bg-seal-600 px-4 py-2 text-sm text-white hover:bg-seal-700 disabled:opacity-50"
              >
                重新分析
              </button>
              <Link to="/" className="text-sm text-ink-600 hover:text-seal-600 hover:underline">
                返回首页
              </Link>
            </div>
            {retryMsg && (
              <p className="mt-2 text-xs text-ink-600" aria-live="polite">
                {retryMsg}
              </p>
            )}
          </div>
        ) : (
          <div className="mt-6 rounded-card border border-ink-300 bg-white p-6">
            <div className="flex items-center gap-2 text-sm text-ink-900">
              <span className="spinner" />
              <span>{PHASE_LABELS[phase]}</span>
              {status?.message && <span className="text-ink-600">· {status.message}</span>}
            </div>
            <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-ink-300">
              <div className="h-full bg-seal-600 transition-all" style={{ width: `${pct}%` }} />
            </div>
            <p className="mt-1 text-xs text-ink-600">{Math.round(pct)}%</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {PHASE_ORDER.filter((p) => p !== "queued").map((p, i) => (
                <span
                  key={p}
                  className={`rounded-full px-2.5 py-1 text-xs ${
                    i < currentIdx
                      ? "bg-pine-100 text-pine-600"
                      : i === currentIdx
                        ? "bg-seal-100 text-seal-600"
                        : "bg-paper-100 text-ink-600"
                  }`}
                >
                  {PHASE_LABELS[p]}
                </span>
              ))}
            </div>
            {error && <p className="mt-3 text-xs text-danger-600">网络错误，正在重试：{error}</p>}
            {status?.warnings?.length > 0 && (
              <p className="mt-3 text-xs text-amber-600">存在 {status.warnings.length} 条警告</p>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
