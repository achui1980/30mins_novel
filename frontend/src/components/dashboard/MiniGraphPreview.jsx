import { categoryColor } from "../../constants";

const MAX_NODES = 5;
// Fixed positions for up to 5 nodes arranged in a pentagon, in a 200x170
// viewBox. A tiny, dependency-free stand-in for the full vis-network force
// graph (GraphTab) — good enough for a Dashboard preview per design spec §8
// ("图谱预览的具体可视化方案...留给实施阶段决定"), and avoids importing the
// 200KB+ vis-network bundle just to render a preview.
const POSITIONS = [
  [100, 20],
  [180, 75],
  [148, 150],
  [52, 150],
  [20, 75],
];

export default function MiniGraphPreview({ mainCharacters, graph }) {
  const nodes = (mainCharacters || []).slice(0, MAX_NODES);
  const positioned = nodes.map((n, i) => ({ ...n, x: POSITIONS[i][0], y: POSITIONS[i][1] }));
  const idSet = new Set(positioned.map((n) => n.id));
  const edges = (graph?.edges || graph?.links || []).filter(
    (e) => idSet.has(e.source) && idSet.has(e.target)
  );

  if (positioned.length === 0) return null;

  return (
    <svg viewBox="0 0 200 170" className="h-40 w-full" role="img" aria-label="人物关系预览图">
      {edges.map((e, i) => {
        const from = positioned.find((n) => n.id === e.source);
        const to = positioned.find((n) => n.id === e.target);
        if (!from || !to) return null;
        return (
          <line
            key={i}
            x1={from.x}
            y1={from.y}
            x2={to.x}
            y2={to.y}
            stroke={categoryColor(e.category)}
            strokeWidth={2}
          />
        );
      })}
      {positioned.map((n) => (
        <g key={n.id}>
          <circle cx={n.x} cy={n.y} r={16} fill="#B33A3A" opacity={0.85} />
          <text x={n.x} y={n.y + 4} textAnchor="middle" fontSize="9" fill="#FAF6EE">
            {(n.label || "").slice(0, 2)}
          </text>
        </g>
      ))}
    </svg>
  );
}
