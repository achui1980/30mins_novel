import { useEffect, useState } from "react";
import { getTimeline } from "../../api";

export default function TimelineTab({ id, setRight }) {
  const [events, setEvents] = useState(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    getTimeline(id)
      .then((r) => setEvents(r.events || []))
      .catch((e) => setError(e.message));
  }, [id]);

  useEffect(() => {
    if (!selected) {
      setRight(<div className="text-sm text-ink-600">点击时间轴上的事件查看详情</div>);
      return () => setRight(null);
    }
    setRight(
      <div>
        <h3 className="font-serif text-sm font-semibold text-ink-900">
          {selected.chapter_title} · 第 {selected.seq + 1} 个事件
        </h3>
        <p className="mt-3 text-sm leading-relaxed text-ink-900">{selected.summary}</p>
        {selected.participants?.length > 0 && (
          <p className="mt-3 text-xs text-ink-600">参与者：{selected.participants.join("、")}</p>
        )}
      </div>
    );
    return () => setRight(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  if (error) {
    return (
      <div className="mx-auto max-w-3xl px-8 py-10 text-ink-600">
        {error}
        <div className="mt-2 text-sm text-ink-600">
          （此功能仅对新处理的作品生效，旧作品请重新上传处理体验。）
        </div>
      </div>
    );
  }
  if (!events) {
    return (
      <div className="mx-auto max-w-3xl px-8 py-10 text-ink-600">
        <span className="spinner" /> 加载中…
      </div>
    );
  }
  if (events.length === 0) {
    return <div className="mx-auto max-w-3xl px-8 py-10 text-ink-600">未生成任何情节事件</div>;
  }

  const groups = [];
  for (const e of events) {
    const last = groups[groups.length - 1];
    if (last && last.chapter_id === e.chapter_id) {
      last.events.push(e);
    } else {
      groups.push({ chapter_id: e.chapter_id, chapter_title: e.chapter_title, events: [e] });
    }
  }

  return (
    <div className="px-8 py-10">
      <p className="mb-4 text-sm text-ink-600">
        按章节顺序排列的关键情节事件，横向滚动查看，点击卡片展开详情。
      </p>
      <div className="flex gap-6 overflow-x-auto pb-4">
        {groups.map((g, gi) => (
          <div key={gi} className="flex-shrink-0">
            <div className="mb-2 text-xs font-semibold text-ink-600">{g.chapter_title}</div>
            <div className="flex gap-2">
              {g.events.map((e) => (
                <button
                  key={e.seq}
                  type="button"
                  onClick={() => setSelected(selected?.seq === e.seq ? null : e)}
                  className={`w-48 rounded-card border p-3 text-left text-sm ${
                    selected?.seq === e.seq
                      ? "border-seal-600 bg-seal-100/30 text-ink-900"
                      : "border-ink-300 bg-white text-ink-900"
                  }`}
                >
                  {e.summary}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
