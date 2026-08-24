import { X } from "lucide-react";

// Global settings gear panel (design spec §2): app-wide reading
// preferences (font size, day/night theme). Distinct from a book's own
// 世界观设定 content (SettingsTab), which stays a normal Dashboard section.
export default function SettingsOverlay({ open, onClose, prefs }) {
  if (!open) return null;
  const { fontSize, theme, stepFontSize, toggleTheme } = prefs;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/30" onClick={onClose}>
      <div
        className="w-[320px] rounded-card border border-ink-300 bg-white p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="font-serif text-base font-semibold text-ink-900">阅读设置</h3>
          <button type="button" onClick={onClose} aria-label="关闭">
            <X size={16} strokeWidth={1.5} className="text-ink-600" />
          </button>
        </div>
        <div className="mt-4">
          <p className="text-xs font-semibold uppercase text-ink-600">字号</p>
          <div className="mt-2 flex items-center gap-2">
            <button type="button" onClick={() => stepFontSize(-1)} className="rounded border border-ink-300 px-3 py-1.5 text-sm">A-</button>
            <span className="text-sm text-ink-900">{fontSize}px</span>
            <button type="button" onClick={() => stepFontSize(1)} className="rounded border border-ink-300 px-3 py-1.5 text-sm">A+</button>
          </div>
        </div>
        <div className="mt-4">
          <p className="text-xs font-semibold uppercase text-ink-600">主题</p>
          <button
            type="button"
            onClick={toggleTheme}
            className="mt-2 rounded border border-ink-300 px-3 py-1.5 text-sm"
          >
            {theme === "night" ? "☀️ 切换为日间" : "🌙 切换为夜间"}
          </button>
        </div>
      </div>
    </div>
  );
}
