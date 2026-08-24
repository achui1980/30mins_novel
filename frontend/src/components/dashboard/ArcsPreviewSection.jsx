export default function ArcsPreviewSection({ ls, onOpenArcs, onOpenStory }) {
  const arcs = ls.arcs || [];
  return (
    <section id="sec-arcs" className="scroll-mt-16 border-b border-ink-300 py-8">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-lg font-semibold text-ink-900">情节脉络</h2>
        <button type="button" onClick={onOpenArcs} className="text-sm text-ink-600 hover:text-seal-600 hover:underline">
          查看完整→
        </button>
      </div>
      {arcs.length === 0 ? (
        <p className="mt-4 text-ink-600">未识别到情节线</p>
      ) : (
        <div className="mt-4 space-y-3">
          {arcs.map((a, i) => (
            <div key={i} className="rounded-card border border-ink-300 bg-white p-4">
              <div className="font-serif font-semibold text-ink-900">{a.title}</div>
              <p className="mt-1 text-sm leading-relaxed text-ink-900">{a.summary}</p>
              {a.member_characters?.length > 0 && (
                <p className="mt-2 text-xs text-ink-600">涉及人物：{a.member_characters.join("、")}</p>
              )}
            </div>
          ))}
        </div>
      )}
      <button
        type="button"
        onClick={onOpenStory}
        className="mt-3 text-sm text-ink-600 hover:text-seal-600 hover:underline"
      >
        查看逐幕剧情正片 →
      </button>
    </section>
  );
}
