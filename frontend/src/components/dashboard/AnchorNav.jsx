import { useAnchorScrollSpy } from "../../hooks/useAnchorScrollSpy";

const SECTIONS = [
  { id: "sec-hero", label: "简介" },
  { id: "sec-characters", label: "人物" },
  { id: "sec-arcs", label: "情节" },
  { id: "sec-timeline", label: "时间" },
  { id: "sec-settings", label: "设定" },
];

export default function AnchorNav() {
  const activeId = useAnchorScrollSpy(SECTIONS.map((s) => s.id));

  function jumpTo(id) {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <nav className="sticky top-0 z-10 -mx-8 flex gap-2 overflow-x-auto border-b border-ink-300 bg-paper-50/95 px-8 py-2 backdrop-blur">
      {SECTIONS.map((s) => (
        <button
          key={s.id}
          type="button"
          onClick={() => jumpTo(s.id)}
          className={
            "shrink-0 rounded-full px-3 py-1 text-xs transition-colors " +
            (activeId === s.id
              ? "bg-ink-900 text-white"
              : "border border-ink-300 text-ink-600 hover:border-seal-600 hover:text-seal-600")
          }
        >
          {s.label}
        </button>
      ))}
    </nav>
  );
}
