import { useEffect, useState } from "react";
import { getBeats, getBeatStory } from "../../api";

export default function StoryTab({ id, setRight }) {
  const [meta, setMeta] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);
  const [beatState, setBeatState] = useState({});

  useEffect(() => {
    setRight(null);
  }, [setRight]);

  useEffect(() => {
    getBeats(id).then(setMeta).catch((e) => setError(e.message));
  }, [id]);

  async function toggleBeat(index) {
    if (open === index) {
      setOpen(null);
      return;
    }
    setOpen(index);
    const existing = beatState[index];
    if (existing && (existing.story || existing.loading)) return;
    setBeatState((s) => ({ ...s, [index]: { loading: true } }));
    try {
      const res = await getBeatStory(id, index);
      setBeatState((s) => ({ ...s, [index]: { loading: false, story: res.story } }));
    } catch (e) {
      setBeatState((s) => ({ ...s, [index]: { loading: false, error: e.message } }));
    }
  }

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
  if (!meta) {
    return (
      <div className="mx-auto max-w-3xl px-8 py-10 text-ink-600">
        <span className="spinner" /> 加载中…
      </div>
    );
  }

  const beats = meta.beats || [];
  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="rounded-card border border-ink-300 bg-white p-6">
        {meta.main_thread && (
          <p className="font-serif text-lg font-semibold text-ink-900">主线：{meta.main_thread}</p>
        )}
        {meta.tone && <p className="mt-2 text-sm text-ink-600">讲述基调：{meta.tone}</p>}
        <p className="mt-2 text-sm text-ink-600">点击任意情节节拍，按需生成该段的故事讲述。</p>
      </div>

      {beats.length === 0 ? (
        <div className="mt-6 text-ink-600">未生成情节节拍</div>
      ) : (
        <div className="mt-6 divide-y divide-ink-300 rounded-card border border-ink-300 bg-white">
          {beats.map((b) => {
            const isOpen = open === b.index;
            const st = beatState[b.index] || {};
            return (
              <div key={b.index}>
                <button
                  type="button"
                  onClick={() => toggleBeat(b.index)}
                  className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-ink-900"
                >
                  <span>
                    {b.index + 1}. {b.title}
                  </span>
                  <span className={isOpen ? "text-seal-600" : "text-ink-600"}>
                    {isOpen ? "▾" : "▸"}
                  </span>
                </button>
                {isOpen && (
                  <div className="px-4 pb-4 text-sm leading-relaxed text-ink-900">
                    {st.loading && (
                      <span>
                        <span className="spinner" /> 生成中…
                      </span>
                    )}
                    {st.error && <span className="text-danger-600">{st.error}</span>}
                    {!st.loading && !st.error && (st.story || "（暂无内容）")}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
