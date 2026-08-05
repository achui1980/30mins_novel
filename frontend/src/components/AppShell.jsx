import { Link, useNavigate } from "react-router-dom";
import { Plus, BookMarked, Trash2 } from "lucide-react";
import { useWorksList } from "../hooks/useWorksList";
import { deleteWork } from "../api";

export default function AppShell({ activeWorkId, right, children }) {
  const { works, loading, refresh } = useWorksList();
  const navigate = useNavigate();

  function openWork(w) {
    navigate(w.phase === "done" ? `/works/${w.work_id}` : `/works/${w.work_id}/processing`);
  }

  function removeWork(w, e) {
    e.stopPropagation();
    if (!window.confirm("确定删除这本书及其所有产出？")) return;
    deleteWork(w.work_id).then(refresh);
  }

  return (
    <div className="flex h-screen bg-paper-50 text-ink-900 font-sans text-sm">
      <aside className="flex w-[140px] shrink-0 flex-col overflow-y-auto border-r border-ink-300 bg-paper-100">
        <Link
          to="/"
          className="flex items-center gap-1.5 px-3 py-4 font-serif text-[15px] font-semibold text-ink-900 hover:text-seal-600"
        >
          <BookMarked size={16} strokeWidth={1.5} />
          <span>书架</span>
        </Link>
        <nav className="flex-1 space-y-0.5 px-1.5">
          {loading && <div className="px-2 py-1 text-xs text-ink-600">加载中…</div>}
          {!loading && works.length === 0 && (
            <div className="px-2 py-1 text-xs text-ink-600">暂无作品</div>
          )}
          {works.map((w) => {
            const active = w.work_id === activeWorkId;
            const bar =
              w.phase === "failed" ? "border-danger-600" : active ? "border-seal-600" : "border-pine-600";
            return (
              <button
                key={w.work_id}
                onClick={() => openWork(w)}
                title={w.title || w.work_id}
                className={`group flex w-full items-center gap-1 rounded-r border-l-[3px] ${bar} py-1.5 pl-2 pr-1 text-left text-xs hover:bg-paper-50 ${
                  active ? "bg-paper-50 font-medium" : ""
                }`}
              >
                <span className="flex-1 truncate">{w.title || w.work_id}</span>
                <Trash2
                  size={12}
                  strokeWidth={1.5}
                  className="shrink-0 text-ink-600 opacity-0 hover:text-danger-600 group-hover:opacity-100"
                  onClick={(e) => removeWork(w, e)}
                />
              </button>
            );
          })}
        </nav>
        <Link
          to="/"
          className="flex items-center gap-1 border-t border-ink-300 px-3 py-3 text-xs text-ink-600 hover:text-seal-600"
        >
          <Plus size={14} strokeWidth={1.5} />
          <span>新建</span>
        </Link>
      </aside>
      <main className="flex-1 overflow-y-auto">{children}</main>
      {right != null && (
        <aside className="w-[200px] shrink-0 overflow-y-auto border-l border-ink-300 bg-paper-100 p-3">
          {right}
        </aside>
      )}
    </div>
  );
}
