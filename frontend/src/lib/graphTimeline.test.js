import { describe, expect, it } from "vitest";
import {
  MAX_BUCKETS,
  PER_CHAPTER_MAX,
  buildBuckets,
  buildChapterOrder,
  buildTransitionIndex,
  firstChapterOrder,
  hasTimeline,
  isVisibleAt,
  mentionSeries,
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
    expect(buckets[0]).toEqual({ label: "第1章", cutoff: 1, chapterId: "ch0001" });
    expect(buckets[19].cutoff).toBe(20);
  });

  it("collapses long books into 16 buckets", () => {
    const buckets = buildBuckets(chapters(100));
    expect(buckets).toHaveLength(16);
    // 第一个桶覆盖 1..6，label 取桶内首章，cutoff 取桶内末章的 order
    expect(buckets[0].label).toBe("第1章");
    expect(buckets[0].cutoff).toBe(6);
    expect(buckets[15].cutoff).toBe(100);
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

describe("mentionSeries", () => {
  it("aggregates mentions into the buckets, boundary chapter included", () => {
    const chs = chapters(100);
    const order = buildChapterOrder(chs);
    const buckets = buildBuckets(chs);
    // buckets[0] 覆盖到 order 6（含），buckets[1] 从 order 7 开始
    const series = mentionSeries(
      { mentions_by_chapter: { ch0001: 1, ch0006: 3, ch0007: 5, ch0100: 2 } },
      buckets,
      order,
    );
    expect(series).toHaveLength(16);
    expect(series[0]).toBe(4);
    expect(series[1]).toBe(5);
    expect(series[15]).toBe(2);
  });

  it("drops mentions in unknown chapters instead of counting them in the first bucket", () => {
    const chs = chapters(4);
    const order = buildChapterOrder(chs);
    const buckets = buildBuckets(chs);
    const series = mentionSeries(
      { mentions_by_chapter: { ch0001: 2, ch9999: 7, "": 5 } },
      buckets,
      order,
    );
    expect(series).toEqual([2, 0, 0, 0]);
  });

  it("buckets by order rather than by chapter id", () => {
    const order = buildChapterOrder(SKEWED);
    const buckets = buildBuckets(SKEWED);
    const series = mentionSeries(
      { mentions_by_chapter: { ch0002: 5, ch0010: 3 } },
      buckets,
      order,
    );
    expect(series).toEqual([3, 5]);
  });

  it("returns all-zero series for nodes without mentions_by_chapter (e.g. places)", () => {
    const chs = chapters(3);
    const buckets = buildBuckets(chs);
    const order = buildChapterOrder(chs);
    expect(mentionSeries({ first_chapter: "ch0001" }, buckets, order)).toEqual([0, 0, 0]);
    expect(mentionSeries({ mentions_by_chapter: {} }, buckets, order)).toEqual([0, 0, 0]);
    expect(mentionSeries(null, buckets, order)).toEqual([0, 0, 0]);
  });

  it("tolerates an empty bucket list", () => {
    expect(mentionSeries({ mentions_by_chapter: { ch0001: 3 } }, [], new Map())).toEqual([]);
    expect(mentionSeries({ mentions_by_chapter: { ch0001: 3 } }, undefined, new Map())).toEqual([]);
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
