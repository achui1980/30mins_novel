// Pure, framework-free helpers for the Dashboard's Hero metadata row.
// Deliberately does NOT fetch full chapter text to compute a novel-wide
// word count: RawTextTab lazy-loads chapter text on scroll by design, and
// eagerly fetching every chapter just to show a word count on the
// Dashboard would undo that lazy-loading and add N extra requests on every
// book open. The backend also doesn't currently expose a precomputed word
// count (see backend/app/pipeline/parse.py's ParsedBook.total_chars, which
// is internal and not surfaced via any API route) and this redesign is
// scoped to frontend-only changes (design spec §1). So the Hero shows
// chapter count + an estimated *panorama* reading time instead of a novel
// word count.
const CHARS_PER_MINUTE = 300; // rough average adult Chinese silent-reading speed

export function estimatePanoramaMinutes(pkg, ls) {
  const parts = [
    ls?.one_liner,
    ls?.story_hook,
    ls?.overview,
    ...(ls?.arcs || []).map((a) => a.summary),
    ...(pkg?.setting_cards || []).map((c) => c.content),
  ].filter(Boolean);
  const totalChars = parts.reduce((sum, text) => sum + text.length, 0);
  return Math.max(1, Math.ceil(totalChars / CHARS_PER_MINUTE));
}

// Returns the first `n` events unchanged, for the Dashboard's 时间轴 teaser.
// Picking the earliest events (rather than "most recent", which has no
// meaning for a book nobody has started reading yet) keeps the teaser
// non-spoiler-heavy while still being a real, truthful sample of the data.
export function pickTimelineTeaser(events, n = 4) {
  return (events || []).slice(0, n);
}
