import { describe, it, expect, beforeEach } from "vitest";
import { getReadingProgress, setReadingProgress, describeProgress, progressKey } from "./readingProgress";

const WORK_ID = "w1";
const CHAPTERS = [
  { chapter: "ch0001", title: "第一章" },
  { chapter: "ch0002", title: "第二章" },
  { chapter: "ch0003", title: "第三章" },
  { chapter: "ch0004", title: "第四章" },
];

beforeEach(() => {
  localStorage.clear();
});

describe("readingProgress", () => {
  it("returns null when nothing is saved", () => {
    expect(getReadingProgress(WORK_ID)).toBeNull();
  });

  it("round-trips through localStorage", () => {
    setReadingProgress(WORK_ID, "ch0002", 5);
    expect(getReadingProgress(WORK_ID)).toEqual({ chapterId: "ch0002", paragraphIndex: 5 });
  });

  it("returns null for corrupted JSON instead of throwing", () => {
    localStorage.setItem(progressKey(WORK_ID), "{not json");
    expect(getReadingProgress(WORK_ID)).toBeNull();
  });

  it("describeProgress computes percent and chapter title", () => {
    setReadingProgress(WORK_ID, "ch0002", 3);
    expect(describeProgress(WORK_ID, CHAPTERS)).toEqual({
      percent: 50,
      chapterTitle: "第二章",
      chapterIndex: 1,
    });
  });

  it("describeProgress returns null when the saved chapter isn't in the list", () => {
    setReadingProgress(WORK_ID, "ch9999", 0);
    expect(describeProgress(WORK_ID, CHAPTERS)).toBeNull();
  });

  it("describeProgress returns null when there is no progress yet", () => {
    expect(describeProgress(WORK_ID, CHAPTERS)).toBeNull();
  });
});
