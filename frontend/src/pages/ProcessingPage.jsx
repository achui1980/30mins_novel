import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { getStatus } from "../api";
import { PHASE_LABELS, PHASE_ORDER } from "../constants";

export default function ProcessingPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const timer = useRef(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const s = await getStatus(id);
        if (cancelled) return;
        setStatus(s);
        if (s.phase === "done") {
          navigate(`/works/${id}`, { replace: true });
          return;
        }
        if (s.phase === "failed") return; // stop polling on failure
        timer.current = setTimeout(poll, 2000);
      } catch (e) {
        if (cancelled) return;
        setError(e.message);
        timer.current = setTimeout(poll, 3000);
      }
    }

    poll();
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [id, navigate]);

  const phase = status?.phase || "queued";
  const failed = phase === "failed";
  const currentIdx = PHASE_ORDER.indexOf(phase);

  // Progress: use per-phase index as base, add extracting fraction if present.
  let pct = 0;
  if (!failed) {
    const base = currentIdx < 0 ? 0 : currentIdx / (PHASE_ORDER.length - 1);
    pct = Math.round(base * 100);
    if (phase === "extracting" && typeof status?.progress === "number") {
      const extractIdx = PHASE_ORDER.indexOf("extracting");
      const span = 1 / (PHASE_ORDER.length - 1);
      pct = Math.round((extractIdx / (PHASE_ORDER.length - 1) + status.progress * span) * 100);
    }
  }

  return (
    <div className="container">
      <Link to="/" className="muted">
        ← 返回首页
      </Link>
      <h1 className="site-title" style={{ marginTop: 12 }}>
        {status?.title || "处理中"}
      </h1>

      {failed ? (
        <div className="center-card">
          <div className="error-banner">
            处理失败：{status?.error || status?.message || "未知错误"}
          </div>
          <Link className="btn" to="/">
            返回首页重试
          </Link>
        </div>
      ) : (
        <div className="center-card">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="spinner" />
            <strong>{PHASE_LABELS[phase] || phase}</strong>
            <span className="muted">{status?.message}</span>
          </div>

          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <div className="muted">{pct}%</div>

          <div className="phase-steps">
            {PHASE_ORDER.filter((p) => p !== "queued").map((p) => {
              const idx = PHASE_ORDER.indexOf(p);
              const cls =
                idx < currentIdx ? "done" : idx === currentIdx ? "active" : "";
              return (
                <span key={p} className={`phase-chip ${cls}`}>
                  {PHASE_LABELS[p]}
                </span>
              );
            })}
          </div>

          {error && <div className="error-banner" style={{ marginTop: 14 }}>{error}</div>}

          {status?.warnings?.length > 0 && (
            <div className="muted" style={{ marginTop: 14, fontSize: 13 }}>
              {status.warnings.length} 条提取警告（部分块被跳过，不影响整体结果）
            </div>
          )}
        </div>
      )}
    </div>
  );
}
