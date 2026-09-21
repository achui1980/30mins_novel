// 章节时间滑块 (design §5.1)。受控组件，只负责显示与回调 —— 分桶逻辑全在
// lib/graphTimeline.js 的 buildBuckets 里，这里不做任何章序计算。
//
// 为什么显示 rangeLabel 而不是 label：一个档的 `label` 是档内**首章**标题，而
// `cutoff`（可见性过滤的依据）是档内**末章**的 order。137 章的作品最后一档是
// `{label: "第129章", cutoff: 137}`，显示 label 会说"读到：第129章"而图上其实
// 已经画到第137章 —— 每个滑块位置都少报最多一整档。rangeLabel 正是为此而加的。

/** 一档要显示的文字。旧形状的 buckets 没有 rangeLabel 时退回 label，避免渲染 undefined。 */
function bucketText(bucket) {
  return (bucket && (bucket.rangeLabel || bucket.label)) || "";
}

export default function ChapterSlider({ buckets, value, onChange }) {
  if (!buckets || buckets.length === 0) return null;

  const last = buckets.length - 1;
  // value 是**档位下标**，不是章节 order —— 这里的 `|| 0` 只是把 NaN/undefined
  // 夹回"最开始"，和 lib 里禁止给未知章节 order 兜 0 是两回事。
  const index = Math.max(0, Math.min(Number(value) || 0, last));
  const currentText = bucketText(buckets[index]);
  const startText = bucketText(buckets[0]);
  const endText = bucketText(buckets[last]);

  return (
    <div className="rounded-card border border-ink-300 bg-white px-4 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="shrink-0 text-sm text-ink-600">时间轴</span>
        {/* 真实章节标题很长（"第一章 风雪惊变–第六章 崖顶疑阵"），一律单行截断，
            完整文字挂在 title 上，避免撑破卡片。 */}
        <span className="min-w-0 truncate text-sm text-ink-900" title={currentText}>
          读到：{currentText}
        </span>
      </div>
      <input
        type="range"
        min={0}
        max={last}
        step={1}
        value={index}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label="章节时间轴"
        className="mt-2 w-full accent-seal-600"
      />
      <div className="mt-1 flex justify-between gap-3 text-xs text-ink-600">
        <span className="min-w-0 truncate" title={startText}>
          {startText}
        </span>
        <span className="min-w-0 truncate text-right" title={endText}>
          {endText}
        </span>
      </div>
    </div>
  );
}
