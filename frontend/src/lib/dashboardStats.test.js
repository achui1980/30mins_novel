import { describe, it, expect } from "vitest";
import { estimatePanoramaMinutes, pickTimelineTeaser } from "./dashboardStats";

describe("estimatePanoramaMinutes", () => {
  it("returns at least 1 minute for a book with almost no summary text", () => {
    expect(estimatePanoramaMinutes({}, {})).toBe(1);
  });

  it("sums one_liner + story_hook + overview + arc summaries + setting cards", () => {
    const ls = {
      one_liner: "a".repeat(100),
      story_hook: "b".repeat(100),
      overview: "c".repeat(100),
      arcs: [{ summary: "d".repeat(100) }, { summary: "e".repeat(100) }],
    };
    const pkg = { setting_cards: [{ content: "f".repeat(200) }] };
    // total = 100*3 + 100*2 + 200 = 700 chars / 300 per-minute = 2.33 -> ceil 3
    expect(estimatePanoramaMinutes(pkg, ls)).toBe(3);
  });
});

describe("pickTimelineTeaser", () => {
  const events = [1, 2, 3, 4, 5, 6].map((seq) => ({ seq }));

  it("returns the first 4 events by default", () => {
    expect(pickTimelineTeaser(events)).toEqual([{ seq: 1 }, { seq: 2 }, { seq: 3 }, { seq: 4 }]);
  });

  it("returns all events if there are fewer than n", () => {
    expect(pickTimelineTeaser([{ seq: 1 }], 4)).toEqual([{ seq: 1 }]);
  });

  it("returns an empty array for null/undefined input", () => {
    expect(pickTimelineTeaser(null)).toEqual([]);
  });
});
