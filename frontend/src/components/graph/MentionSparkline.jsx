// 人物出场曲线 (design §5.4)。无依赖内联 SVG，和 MiniGraphPreview 同一路子。
//
// 柱子的计算（一章一根、按 order 排、超 cutoff 标 dimmed）和峰值全部走
// lib/graphTimeline.js，这里不重算。刻意不在组件里写 Math.max(...counts)：
// 空数组的 Math.max 是 -Infinity 而不是 0，而 mentionPeak 空/全 0 都返回 0。
//
// 三种真实数据都必须画得出来（或干净地不画），不能抛异常：
//  - 地点节点根本没有 mentions_by_chapter 字段；
//  - 只靠关系入场的人物 mentions_by_chapter 是 {}（全 0 的平坦曲线）；
//  - mentions_by_chapter 里有不在 chapters 里的章节 id（mentionBars 直接丢弃）。

import { mentionBars, mentionPeak } from "../../lib/graphTimeline";

const WIDTH = 220;
const HEIGHT = 44;
const GAP = 1;
const MIN_BAR = 2;

export default function MentionSparkline({ node, chapters, cutoff }) {
  const bars = mentionBars(node, chapters, cutoff);
  if (bars.length === 0) return null;

  const peak = mentionPeak(bars);
  // peak === 0 = 没有任何按章提及（地点节点 / 只靠关系入场的人物）：不画空图表。
  // 提前返回同时保证下面那个除法永远不会除 0。
  if (peak <= 0) return null;

  const slot = WIDTH / bars.length;
  const barWidth = Math.max(1, slot - GAP);

  return (
    <div className="mt-2">
      <svg
        width={WIDTH}
        height={HEIGHT}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label="按章提及次数"
      >
        {bars.map((bar, i) => {
          const height = bar.count === 0 ? 0 : Math.max(MIN_BAR, (bar.count / peak) * (HEIGHT - 4));
          return (
            <rect
              key={bar.chapterId}
              x={i * slot}
              y={HEIGHT - height}
              width={barWidth}
              height={height}
              className={bar.dimmed ? "fill-ink-300" : "fill-amber-600"}
            />
          );
        })}
      </svg>
      <p className="mt-1 text-xs text-ink-600">
        按章提及 · 峰值 {peak} 次（共 {bars.length} 章）
      </p>
    </div>
  );
}
