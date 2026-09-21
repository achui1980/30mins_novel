import { describe, expect, it } from "vitest";
import {
  MAX_BUCKETS,
  PER_CHAPTER_MAX,
  buildBuckets,
  buildChapterOrder,
  buildTimeline,
  buildTransitionIndex,
  firstChapterOrder,
  hasTimeline,
  isVisibleAt,
  mentionBars,
  mentionPeak,
  pairKey,
} from "./graphTimeline";

function chapters(n) {
  return Array.from({ length: n }, (_, i) => ({
    id: `ch${String(i + 1).padStart(4, "0")}`,
    title: `第${i + 1}章`,
    order: i + 1,
  }));
}

// 字典序与 order 故意相反：ch0002 排在 ch0010 之前，但它的 order 更大。
// 任何"拿 chapter_id 字符串比大小"的实现都会在这个 fixture 上翻车。
const SKEWED = [
  { id: "ch0002", title: "后章", order: 9 },
  { id: "ch0010", title: "前章", order: 2 },
];

describe("hasTimeline", () => {
  it("requires a non-empty top-level chapters array", () => {
    expect(hasTimeline(null)).toBe(false);
    expect(hasTimeline({})).toBe(false);
    expect(hasTimeline({ chapters: [] })).toBe(false);
    expect(hasTimeline({ chapters: chapters(1) })).toBe(true);
  });

  it("does not accept other timeline-ish keys as a substitute", () => {
    // 降级判定只有这一个闸门：顶层 chapters 缺失就是旧版本作品。
    expect(hasTimeline({ transitions: [{ pair: ["a", "b"] }] })).toBe(false);
    expect(hasTimeline({ nodes: [{ id: "a", first_chapter: "ch0001" }] })).toBe(false);
    expect(hasTimeline({ chapters: "ch0001" })).toBe(false);
  });
});

describe("buildChapterOrder", () => {
  it("maps chapter id to order", () => {
    const map = buildChapterOrder(chapters(2));
    expect(map.get("ch0001")).toBe(1);
    expect(map.get("ch0002")).toBe(2);
  });

  it("tolerates empty input", () => {
    expect(buildChapterOrder(undefined).size).toBe(0);
  });

  it("keeps order values verbatim even when they disagree with id order", () => {
    const map = buildChapterOrder(SKEWED);
    expect(map.get("ch0002")).toBe(9);
    expect(map.get("ch0010")).toBe(2);
  });

  it("drops chapters with a non-numeric order instead of defaulting them to 0", () => {
    const map = buildChapterOrder([
      { id: "ch0001", order: 1 },
      { id: "ch0002" },
      { id: "ch0003", order: "第三" },
    ]);
    expect(map.get("ch0001")).toBe(1);
    expect(map.has("ch0002")).toBe(false);
    expect(map.has("ch0003")).toBe(false);
    expect(map.size).toBe(1);
  });
});

describe("buildBuckets", () => {
  it("pins the bucketing thresholds", () => {
    expect(PER_CHAPTER_MAX).toBe(20);
    expect(MAX_BUCKETS).toBe(16);
  });

  it("returns one bucket per chapter at or below the per-chapter cap", () => {
    const buckets = buildBuckets(chapters(20));
    expect(buckets).toHaveLength(20);
    expect(buckets[0]).toEqual({
      label: "第1章",
      rangeLabel: "第1章",
      cutoff: 1,
      chapterId: "ch0001",
    });
    expect(buckets[19].cutoff).toBe(20);
  });

  it("collapses long books into 16 buckets", () => {
    const buckets = buildBuckets(chapters(100));
    expect(buckets).toHaveLength(16);
    // 第一个桶覆盖 1..6，label 取桶内首章，cutoff 取桶内末章的 order
    expect(buckets[0].label).toBe("第1章");
    expect(buckets[0].cutoff).toBe(6);
    // chapterId 和 cutoff 必须是同一章（末章），不是首章。
    expect(buckets[0].chapterId).toBe("ch0006");
    expect(buckets[15].cutoff).toBe(100);
    expect(buckets[15].chapterId).toBe("ch0100");
  });

  it("gives every multi-chapter bucket a rangeLabel covering what it really includes", () => {
    // 滑块显示 rangeLabel。只显示首章标题会比 cutoff 少报最多一整档，
    // 例如 100 章时 buckets[0] 是 第1章–第6章 而 cutoff 是 6。
    const buckets = buildBuckets(chapters(100));
    expect(buckets[0].rangeLabel).toBe("第1章–第6章");
    expect(buckets[15].rangeLabel).toBe("第94章–第100章");
    // 每一档的 rangeLabel 都必须以 cutoff 那一章收尾，一档都不能少报。
    for (const b of buckets) {
      expect(b.rangeLabel.endsWith(`第${b.cutoff}章`)).toBe(true);
    }
  });

  it("uses the plain chapter title as rangeLabel when a bucket holds one chapter", () => {
    expect(buildBuckets(chapters(3)).map((b) => b.rangeLabel)).toEqual([
      "第1章",
      "第2章",
      "第3章",
    ]);
    // 折叠分支里也会出现只含一章的档（21 章 / 16 档）。
    const collapsed = buildBuckets(chapters(21));
    expect(collapsed[0].rangeLabel).toBe("第1章");
    expect(collapsed[0].cutoff).toBe(1);
  });

  it("falls back to the chapter id when a chapter has no title", () => {
    const buckets = buildBuckets([{ id: "ch0001", order: 1 }]);
    expect(buckets[0].label).toBe("ch0001");
    expect(buckets[0].rangeLabel).toBe("ch0001");
  });

  it("switches to collapsed buckets at exactly one chapter over the cap", () => {
    // 阈值两侧各钉一次：20 章一章一档，21 章折叠成 16 档。
    expect(buildBuckets(chapters(20))).toHaveLength(20);
    expect(buildBuckets(chapters(21))).toHaveLength(16);
    expect(buildBuckets(chapters(21))[15].cutoff).toBe(21);
  });

  it("honours explicit threshold overrides", () => {
    const buckets = buildBuckets(chapters(5), { perChapterMax: 3, maxBuckets: 2 });
    expect(buckets.map((b) => b.cutoff)).toEqual([2, 5]);
  });

  it("sorts by order rather than array position", () => {
    const buckets = buildBuckets([
      { id: "ch0002", title: "第二章", order: 2 },
      { id: "ch0001", title: "第一章", order: 1 },
    ]);
    expect(buckets.map((b) => b.chapterId)).toEqual(["ch0001", "ch0002"]);
  });

  it("sorts by order even when chapter ids sort the other way", () => {
    const buckets = buildBuckets(SKEWED);
    expect(buckets.map((b) => b.chapterId)).toEqual(["ch0010", "ch0002"]);
    expect(buckets.map((b) => b.label)).toEqual(["前章", "后章"]);
    expect(buckets.map((b) => b.cutoff)).toEqual([2, 9]);
  });

  it("returns an empty array for empty input", () => {
    expect(buildBuckets([])).toEqual([]);
    expect(buildBuckets(undefined)).toEqual([]);
  });
});

describe("firstChapterOrder", () => {
  it("reads the order from the lookup table, not from the id", () => {
    const order = buildChapterOrder(SKEWED);
    expect(firstChapterOrder({ first_chapter: "ch0002" }, order)).toBe(9);
    expect(firstChapterOrder({ first_chapter: "ch0010" }, order)).toBe(2);
  });

  it("returns 0 for missing or unknown chapters", () => {
    const order = buildChapterOrder(chapters(3));
    expect(firstChapterOrder({}, order)).toBe(0);
    expect(firstChapterOrder({ first_chapter: "" }, order)).toBe(0);
    expect(firstChapterOrder({ first_chapter: "ch9999" }, order)).toBe(0);
  });
});

describe("isVisibleAt", () => {
  const order = buildChapterOrder(chapters(10));

  it("hides items whose first chapter is later than the cutoff", () => {
    expect(isVisibleAt({ first_chapter: "ch0005" }, 4, order)).toBe(false);
    expect(isVisibleAt({ first_chapter: "ch0005" }, 5, order)).toBe(true);
    expect(isVisibleAt({ first_chapter: "ch0005" }, 9, order)).toBe(true);
  });

  it("keeps items with no or unknown first chapter always visible", () => {
    expect(isVisibleAt({}, 1, order)).toBe(true);
    expect(isVisibleAt({ first_chapter: "" }, 1, order)).toBe(true);
    expect(isVisibleAt({ first_chapter: "ch9999" }, 1, order)).toBe(true);
  });

  it("compares by order, not by chapter id", () => {
    const skewed = buildChapterOrder(SKEWED);
    // ch0010 的 order 是 2，ch0002 的 order 是 9
    expect(isVisibleAt({ first_chapter: "ch0010" }, 2, skewed)).toBe(true);
    expect(isVisibleAt({ first_chapter: "ch0002" }, 2, skewed)).toBe(false);
    expect(isVisibleAt({ first_chapter: "ch0002" }, 9, skewed)).toBe(true);
  });
});

describe("mentionBars", () => {
  // 原 mentionSeries 的 5 个用例全部按"一章一根柱子"的新形状迁移过来，没有删覆盖。
  it("emits one bar per chapter, in order, with the raw per-chapter counts", () => {
    const chs = chapters(4);
    const bars = mentionBars({ mentions_by_chapter: { ch0001: 1, ch0003: 5 } }, chs, 4);
    expect(bars).toHaveLength(4);
    expect(bars.map((b) => b.chapterId)).toEqual(["ch0001", "ch0002", "ch0003", "ch0004"]);
    expect(bars.map((b) => b.count)).toEqual([1, 0, 5, 0]);
  });

  it("does NOT collapse a long book — one bar per chapter even at 137 chapters", () => {
    // 137 章要出 137 根柱子；折叠成 16 根是分辨率变化，不是这里能做的决定。
    expect(mentionBars({ mentions_by_chapter: {} }, chapters(137), 137)).toHaveLength(137);
  });

  it("dims chapters strictly after the cutoff, keeping the cutoff chapter lit", () => {
    const bars = mentionBars({ mentions_by_chapter: {} }, chapters(4), 2);
    // 边界就压在 cutoff 上：order === 2 必须亮，order === 3 必须暗。
    expect(bars.map((b) => b.dimmed)).toEqual([false, false, true, true]);
  });

  it("ignores mention keys that are not in the chapter list", () => {
    const bars = mentionBars(
      { mentions_by_chapter: { ch0001: 2, ch9999: 7, "": 5 } },
      chapters(3),
      3,
    );
    expect(bars).toHaveLength(3);
    expect(bars.map((b) => b.count)).toEqual([2, 0, 0]);
  });

  it("orders and dims by chapter order, not by chapter id", () => {
    const bars = mentionBars({ mentions_by_chapter: { ch0002: 5, ch0010: 3 } }, SKEWED, 2);
    // ch0010 的 order 是 2（亮），ch0002 的 order 是 9（暗）—— 按 id 比大小会反过来。
    expect(bars.map((b) => b.chapterId)).toEqual(["ch0010", "ch0002"]);
    expect(bars.map((b) => b.count)).toEqual([3, 5]);
    expect(bars.map((b) => b.dimmed)).toEqual([false, true]);
  });

  it("yields all-zero bars for nodes without mentions_by_chapter (e.g. places)", () => {
    const chs = chapters(3);
    expect(mentionBars({ first_chapter: "ch0001" }, chs, 3).map((b) => b.count)).toEqual([0, 0, 0]);
    expect(mentionBars({ mentions_by_chapter: {} }, chs, 3).map((b) => b.count)).toEqual([0, 0, 0]);
    expect(mentionBars(null, chs, 3).map((b) => b.count)).toEqual([0, 0, 0]);
    expect(mentionBars(undefined, chs, 3)).toHaveLength(3);
  });

  it("tolerates an empty or malformed chapter list", () => {
    const node = { mentions_by_chapter: { ch0001: 3 } };
    expect(mentionBars(node, [], 1)).toEqual([]);
    expect(mentionBars(node, undefined, 1)).toEqual([]);
    expect(mentionBars(node, [{ chapter: "ch0001", summary: "..." }], 1)).toEqual([]);
  });
});

describe("mentionPeak", () => {
  it("returns the largest count", () => {
    expect(mentionPeak([{ count: 1 }, { count: 5 }, { count: 3 }])).toBe(5);
  });

  it("returns 0 for an empty or flat series so callers can guard division", () => {
    // 只靠关系入场的人物 mentions_by_chapter 是 {}，曲线全 0 —— 不能炸。
    expect(mentionPeak([])).toBe(0);
    expect(mentionPeak(undefined)).toBe(0);
    expect(mentionPeak([{ count: 0 }, { count: 0 }])).toBe(0);
    expect(mentionPeak(mentionBars({}, chapters(3), 3))).toBe(0);
  });
});

describe("buildTimeline", () => {
  it("reads the chapter list off the graph's own top-level chapters", () => {
    const graph = {
      chapters: chapters(3),
      transitions: [{ pair: ["b", "a"], steps: [{ chapter_id: "ch0001" }], confirmed: true }],
      // 形状不同的另一份章节列表，故意放在这里：取错源头就会被下面的断言抓到。
      layered_summary: { chapters: [{ chapter: "ch0001", summary: "..." }] },
    };
    const t = buildTimeline(graph);
    expect(t.hasTimeline).toBe(true);
    expect(t.buckets.map((b) => b.cutoff)).toEqual([1, 2, 3]);
    expect(t.chapters.map((c) => c.id)).toEqual(["ch0001", "ch0002", "ch0003"]);
    expect(t.orderMap.get("ch0003")).toBe(3);
    expect(t.transitionIndex.get(pairKey("a", "b")).confirmed).toBe(true);
  });

  it("degrades to an inert-but-safe timeline for a graph with no chapters", () => {
    const t = buildTimeline({ transitions: [] });
    expect(t.hasTimeline).toBe(false);
    expect(t.buckets).toEqual([]);
    expect(t.chapters).toEqual([]);
    expect(t.orderMap.size).toBe(0);
    expect(t.transitionIndex.size).toBe(0);
    expect(buildTimeline(null).hasTimeline).toBe(false);
    expect(buildTimeline(undefined).buckets).toEqual([]);
  });

  it("states the trap: the wrong chapter shape yields empty buckets, not an error", () => {
    // layered_summary.chapters 的形状是 {chapter, summary} —— 没有 id / order。
    // 顶层 chapters 非空所以 hasTimeline 仍是 true，但 buckets/orderMap 是空的，
    // 于是 firstChapterOrder 对所有节点都返回 0 = 全部可见：时间轴看着在，实际不过滤。
    const graph = { chapters: [{ chapter: "ch0001", summary: "..." }] };
    expect(hasTimeline(graph)).toBe(true);
    const t = buildTimeline(graph);
    expect(t.buckets).toEqual([]);
    expect(t.chapters).toEqual([]);
    expect(t.orderMap.size).toBe(0);
    expect(isVisibleAt({ first_chapter: "ch0001" }, 0, t.orderMap)).toBe(true);
  });

  it("forwards bucketing options", () => {
    const t = buildTimeline({ chapters: chapters(5) }, { perChapterMax: 3, maxBuckets: 2 });
    expect(t.buckets.map((b) => b.cutoff)).toEqual([2, 5]);
  });
});

describe("pairKey / buildTransitionIndex", () => {
  it("is order independent", () => {
    expect(pairKey("a", "b")).toBe(pairKey("b", "a"));
  });

  it("normalises to the lexicographically smaller node id first", () => {
    expect(pairKey("b", "a")).toBe("a|b");
    expect(pairKey("a", "b")).toBe("a|b");
  });

  it("indexes transitions by node pair", () => {
    const index = buildTransitionIndex([
      { pair: ["a", "b"], steps: [{ chapter_id: "ch0001", category: "朋友" }], confirmed: true },
    ]);
    expect(index.get(pairKey("b", "a")).confirmed).toBe(true);
  });

  it("is reachable from an edge's (source, target) in either direction", () => {
    const t = { pair: ["n2", "n1"], steps: [{ chapter_id: "ch0001", category: "朋友" }], confirmed: false };
    const index = buildTransitionIndex([t]);
    expect(index.size).toBe(1);
    expect(index.get("n1|n2")).toBe(t);
    expect(index.get(pairKey("n1", "n2"))).toBe(t);
    expect(index.get(pairKey("n2", "n1"))).toBe(t);
  });

  it("preserves steps exactly as received", () => {
    const steps = [
      { chapter_id: "ch0010", category: "朋友" },
      { chapter_id: "ch0002", category: "敌人" },
    ];
    const index = buildTransitionIndex([{ pair: ["a", "b"], steps, confirmed: true }]);
    const found = index.get(pairKey("a", "b"));
    expect(found.steps).toBe(steps);
    expect(found.steps.map((s) => s.chapter_id)).toEqual(["ch0010", "ch0002"]);
  });

  it("skips malformed entries and tolerates empty input", () => {
    const index = buildTransitionIndex([{ pair: ["only"] }, null, { steps: [] }]);
    expect(index.size).toBe(0);
    expect(buildTransitionIndex(undefined).size).toBe(0);
  });
});
