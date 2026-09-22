import { useEffect, useState } from "react";
import { getTimeline } from "../../api";
import { pickTimelineTeaser } from "../../lib/dashboardStats";

export default function TimelinePreviewSection({ id, onOpenTimeline }) {
  const [events, setEvents] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getTimeline(id)
      .then((r) => {
        if (!cancelled) setEvents(r.events || []);
      })
      .catch(() => {
        if (!cancelled) setEvents([]);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const teaser = pickTimelineTeaser(events, 4);

  return (
    <section id="sec-timeline" className="scroll-mt-[52px] border-b border-ink-300 py-8">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-lg font-semibold text-ink-900">时间轴</h2>
        <button type="button" onClick={onOpenTimeline} className="text-sm text-ink-600 hover:text-seal-600 hover:underline">
          查看完整→
        </button>
      </div>
      {events === null && <p className="mt-4 text-ink-600">加载中…</p>}
      {events?.length === 0 && <p className="mt-4 text-ink-600">未生成任何情节事件</p>}
      {teaser.length > 0 && (
        <div className="relative mt-4 border-l-2 border-ink-300 pl-6">
          {teaser.map((e) => (
            <div key={e.seq} className="relative mb-4">
              <span
                aria-hidden="true"
                className="absolute -left-[29px] top-1 h-3 w-3 rounded-full border-2 border-paper-50 bg-seal-600"
              />
              <p className="text-xs font-semibold text-ink-600">{e.chapter_title}</p>
              <p className="mt-1 text-sm text-ink-900">{e.summary}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
