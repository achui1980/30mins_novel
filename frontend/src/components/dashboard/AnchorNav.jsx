import { useAnchorScrollSpy } from "../../hooks/useAnchorScrollSpy";

// Was 5 items while Dashboard rendered 6 sections: 内容简介 and 推荐问题 had no
// id at all and could not be reached, and the "简介" item pointed at sec-hero
// rather than the actual overview. Now one item per section, and `scroll-mt` on
// every section matches this nav's real height (~41px → 52px with breathing
// room) instead of the old hardcoded 64px that overshot by 32px.
const SECTIONS = [
  { id: "sec-overview", label: "梗概" },
  { id: "sec-questions", label: "提问" },
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
    <nav
      aria-label="页内导航"
      className="sticky top-0 z-10 -mx-6 flex gap-2 overflow-x-auto border-b border-ink-300 bg-paper-50/95 px-6 py-2 backdrop-blur md:-mx-8 md:px-8"
    >
      {SECTIONS.map((s) => (
        <button
          key={s.id}
          type="button"
          onClick={() => jumpTo(s.id)}
          aria-current={activeId === s.id ? "true" : undefined}
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
