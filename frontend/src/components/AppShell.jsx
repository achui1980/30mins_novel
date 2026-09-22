import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, BookMarked, Trash2 } from "lucide-react";
import { useWorksList } from "../hooks/useWorksList";
import { deleteWork } from "../api";
import { PHASE_LABELS } from "../constants";

// Deterministic cover tones so two works with the same title are still
// distinguishable in the shelf (the previous 140px / text-xs / truncate shelf
// rendered ten copies of 《白夜行》 as ten identical rows).
const COVER_TONES = [
  "bg-seal-600",
  "bg-pine-600",
  "bg-amber-600",
  "bg-ink-700",
  "bg-ink-500",
];

function toneFor(workId) {
  let h = 0;
  for (let i = 0; i < workId.length; i += 1) h = (h * 31 + workId.charCodeAt(i)) % 9973;
  return COVER_TONES[h % COVER_TONES.length];
}

function coverChar(title, workId) {
  const t = (title || "").trim();
  return t ? Array.from(t)[0] : workId.slice(0, 1).toUpperCase();
}

/**
 * Four-column app shell.
 *
 *   shelf 200px (lg+) | view rail 76px (md+) | main | context rail 300px (xl+)
 *
 * `views` is optional: HomePage and ProcessingPage render without it and get
 * the old three-column behaviour. When present, the reader gets a persistent
 * view switcher (desktop rail + mobile bottom tab bar) instead of the previous
 * `fixed inset-0 z-40` full-screen overlays.
 *
 * z-index scale: 10 sticky in-content · 30 mobile tab bar · 40 overlays · 50 floats.
 */
export default function AppShell({
  activeWorkId,
  title,
  views,
  activeView,
  onView,
  right,
  children,
}) {
  const { works, loading, error, refresh } = useWorksList();
  const [deleteError, setDeleteError] = useState("");
  const navigate = useNavigate();

  // Titles that appear more than once need a disambiguating id suffix.
  const dupTitles = useMemo(() => {
    const seen = new Map();
    works.forEach((w) => {
      const t = w.title || w.work_id;
      seen.set(t, (seen.get(t) || 0) + 1);
    });
    return new Set([...seen.entries()].filter(([, n]) => n > 1).map(([t]) => t));
  }, [works]);

  function openWork(w) {
    navigate(w.phase === "done" ? `/works/${w.work_id}` : `/works/${w.work_id}/processing`);
  }

  function removeWork(w, e) {
    e.stopPropagation();
    if (!window.confirm(`确定删除《${w.title || w.work_id}》及其所有产出？`)) return;
    setDeleteError("");
    deleteWork(w.work_id)
      .then(refresh)
      .catch((err) => setDeleteError(err.message || "删除失败"));
  }

  return (
    <div className="flex h-dvh bg-paper-50 font-sans text-sm text-ink-900">
      {/* ---- shelf ---------------------------------------------------- */}
      <aside className="hidden w-[200px] shrink-0 flex-col overflow-y-auto border-r border-ink-300 bg-paper-100 lg:flex">
        <Link
          to="/"
          className="flex items-center gap-1.5 px-3 py-4 font-serif text-[15px] font-semibold text-ink-900 hover:text-seal-600"
        >
          <BookMarked size={16} strokeWidth={1.5} />
          <span>书架</span>
          {works.length > 0 && (
            <span className="ml-auto text-[11px] font-normal tabular-nums text-ink-500">
              {works.length}
            </span>
          )}
        </Link>
        <nav className="flex-1 space-y-0.5 px-1.5" aria-label="作品列表">
          {error && (
            <div className="mb-1 rounded-card border border-danger-600/40 bg-danger-600/5 px-2 py-1 text-xs text-danger-600">
              加载作品列表失败
            </div>
          )}
          {deleteError && (
            <div className="mb-1 rounded-card border border-danger-600/40 bg-danger-600/5 px-2 py-1 text-xs text-danger-600">
              {deleteError}
            </div>
          )}
          {loading && <div className="px-2 py-1 text-xs text-ink-600">加载中…</div>}
          {!loading && works.length === 0 && (
            <div className="px-2 py-1 text-xs text-ink-600">暂无作品</div>
          )}
          {works.map((w) => {
            const active = w.work_id === activeWorkId;
            const label = w.title || w.work_id;
            const meta =
              w.phase !== "done"
                ? PHASE_LABELS[w.phase] || w.phase
                : w.granularity === "complete"
                  ? "完整档"
                  : "快速档";
            return (
              <div key={w.work_id} className="group relative">
                <button
                  type="button"
                  onClick={() => openWork(w)}
                  title={label}
                  aria-current={active ? "true" : undefined}
                  className={`flex w-full items-start gap-2.5 rounded-card px-2 py-2 pr-7 text-left transition-colors hover:bg-paper-50 ${
                    active ? "bg-paper-50 ring-1 ring-ink-300" : ""
                  }`}
                >
                  <span
                    aria-hidden="true"
                    className={`mt-0.5 flex h-10 w-8 shrink-0 items-center justify-center rounded-[3px] font-serif text-sm text-white shadow-sm2 ${toneFor(w.work_id)}`}
                  >
                    {coverChar(w.title, w.work_id)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span
                      className={`block text-xs leading-snug line-clamp-2 ${active ? "font-semibold" : "font-medium"}`}
                    >
                      {label}
                    </span>
                    <span className="mt-0.5 block text-[11px] text-ink-500">
                      {meta}
                      {dupTitles.has(label) && ` · #${w.work_id.slice(0, 4)}`}
                    </span>
                  </span>
                </button>
                <button
                  type="button"
                  aria-label={`删除《${label}》`}
                  onClick={(e) => removeWork(w, e)}
                  className="absolute right-1 top-2 rounded p-1 text-ink-400 opacity-0 transition-opacity hover:text-danger-600 focus-visible:opacity-100 group-hover:opacity-100"
                >
                  <Trash2 size={13} strokeWidth={1.5} />
                </button>
              </div>
            );
          })}
        </nav>
        <Link
          to="/"
          className="flex items-center gap-1 border-t border-ink-300 px-3 py-3 text-xs text-ink-600 hover:text-seal-600"
        >
          <Plus size={14} strokeWidth={1.5} />
          <span>上传新书</span>
        </Link>
      </aside>

      {/* ---- view rail (desktop) -------------------------------------- */}
      {views && (
        <nav
          aria-label="视图切换"
          className="hidden w-[76px] shrink-0 flex-col items-center gap-1 border-r border-ink-300 bg-paper-100 py-3 md:flex"
        >
          {views.map((v) => {
            const Icon = v.icon;
            const on = v.key === activeView;
            return (
              <div key={v.key} className="flex w-full flex-col items-center">
                {v.divider && <span aria-hidden="true" className="my-1.5 h-px w-8 bg-ink-300" />}
                <button
                  type="button"
                  onClick={() => onView?.(v.key)}
                  aria-current={on ? "page" : undefined}
                  className={`flex w-[60px] flex-col items-center gap-1 rounded-btn px-1 py-2 text-[11px] transition-colors ${
                    on
                      ? "bg-seal-600 font-medium text-white"
                      : "text-ink-600 hover:bg-paper-200 hover:text-ink-900"
                  }`}
                >
                  <Icon size={18} strokeWidth={1.5} />
                  <span>{v.label}</span>
                </button>
              </div>
            );
          })}
        </nav>
      )}

      {/* ---- main ----------------------------------------------------- */}
      <main className={`flex-1 overflow-y-auto ${views ? "pb-14 md:pb-0" : ""}`}>
        {views && (
          <header className="flex items-center gap-2 border-b border-ink-300 px-4 py-2 lg:hidden">
            <Link
              to="/"
              className="flex shrink-0 items-center gap-1 text-xs text-ink-600 hover:text-seal-600"
            >
              <BookMarked size={14} strokeWidth={1.5} />
              <span>书架</span>
            </Link>
            {title && (
              <span className="min-w-0 truncate font-serif text-sm font-semibold">{title}</span>
            )}
          </header>
        )}
        {children}
      </main>

      {/* ---- context rail -------------------------------------------- */}
      {right != null && (
        <aside
          aria-label="上下文"
          className="hidden w-[300px] shrink-0 overflow-y-auto border-l border-ink-300 bg-paper-100 p-4 pt-14 xl:flex xl:flex-col"
        >
          {right}
        </aside>
      )}

      {/* ---- view tab bar (mobile) ----------------------------------- */}
      {views && (
        <nav
          aria-label="视图切换"
          className="fixed inset-x-0 bottom-0 z-30 flex border-t border-ink-300 bg-paper-100 md:hidden"
        >
          {views.map((v) => {
            const Icon = v.icon;
            const on = v.key === activeView;
            return (
              <button
                key={v.key}
                type="button"
                onClick={() => onView?.(v.key)}
                aria-current={on ? "page" : undefined}
                className={`flex min-h-[52px] flex-1 flex-col items-center justify-center gap-0.5 text-[10px] transition-colors ${
                  on ? "text-seal-600" : "text-ink-500"
                }`}
              >
                <Icon size={17} strokeWidth={1.5} />
                <span>{v.label}</span>
              </button>
            );
          })}
        </nav>
      )}
    </div>
  );
}
