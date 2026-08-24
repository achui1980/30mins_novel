// Shared localStorage-backed reading-progress helpers for a single work.
// Used by RawTextTab (writes progress as the user scrolls) and by the
// Dashboard's Hero section (reads it to show "原文已读 N%（第 X 章）").
export function progressKey(workId) {
  return `novel_kg_reader_progress_${workId}`;
}

// Returns { chapterId, paragraphIndex } or null if nothing saved / corrupted.
export function getReadingProgress(workId) {
  const raw = localStorage.getItem(progressKey(workId));
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed?.chapterId !== "string") return null;
    return { chapterId: parsed.chapterId, paragraphIndex: Number(parsed.paragraphIndex) || 0 };
  } catch {
    return null;
  }
}

export function setReadingProgress(workId, chapterId, paragraphIndex) {
  localStorage.setItem(progressKey(workId), JSON.stringify({ chapterId, paragraphIndex }));
}

// Given the saved progress and the book's chapter list (ls.chapters, in
// reading order), returns a small summary for display, or null if there's
// no progress yet or the chapter can't be found (e.g. stale/corrupted id).
export function describeProgress(workId, chapters) {
  const progress = getReadingProgress(workId);
  if (!progress || !chapters?.length) return null;
  const index = chapters.findIndex((c) => c.chapter === progress.chapterId);
  if (index === -1) return null;
  const percent = Math.round(((index + 1) / chapters.length) * 100);
  const title = chapters[index].title || chapters[index].chapter;
  return { percent, chapterTitle: title, chapterIndex: index };
}
