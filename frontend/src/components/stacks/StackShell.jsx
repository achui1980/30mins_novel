import { ArrowLeft } from "lucide-react";

// Full-screen "stack sub-page" chrome shared by all 5 deep-dive pages
// (design spec §4): a fixed overlay that covers the entire viewport
// (including AppShell's left bookshelf), a "← 返回" header, and an optional
// right detail rail for pages that still use the AppShell `setRight`
// pattern (design spec §5). `right == null` renders a single, wider column
// instead — used by the 原文/剧情正片 stack pages for true immersion.
export default function StackShell({ title, onBack, right, children }) {
  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-paper-50">
      <header className="flex items-center gap-3 border-b border-ink-300 bg-paper-100 px-6 py-3">
        <button type="button" onClick={onBack} className="flex items-center gap-1 text-sm text-ink-600 hover:text-seal-600">
          <ArrowLeft size={16} strokeWidth={1.5} />
          返回
        </button>
        <h1 className="font-serif text-base font-semibold text-ink-900">{title}</h1>
      </header>
      {right != null ? (
        <div className="flex flex-1 overflow-hidden">
          <main className="flex-1 overflow-y-auto">{children}</main>
          <aside className="w-[200px] shrink-0 overflow-y-auto border-l border-ink-300 bg-paper-100 p-3">
            {right}
          </aside>
        </div>
      ) : (
        <main className="flex-1 overflow-y-auto">{children}</main>
      )}
    </div>
  );
}
