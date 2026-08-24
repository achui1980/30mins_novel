# Reader Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the reader's 9-tab bar with a panorama-first Dashboard (single scrollable page) plus stack-based full-screen sub-pages, per `docs/superpowers/specs/2026-08-22-reader-dashboard-redesign-design.md`.

**Architecture:** `ReaderPage.jsx` keeps a single always-mounted `<AppShell><Dashboard/></AppShell>` (so Dashboard scroll position survives navigation) and renders a sibling full-viewport `position:fixed` stack overlay when `activeStack` is non-null. Three of the five stack pages (Graph/Arcs/Timeline) reuse their existing Tab components **completely unmodified** by giving each stack wrapper its own local `setRight` state and rendering it inside a `StackShell` right rail — this is the trick that preserves the `setRight` contract without AppShell involvement. The other two (RawText/Story) render single-column/immersive, ignoring whatever their wrapped Tab pushes into `setRight`. Font/theme prefs and reading-progress localStorage logic are lifted out of `RawTextTab.jsx` into two small pure/hook modules so a new global settings gear and the Dashboard Hero can read/control the same state. Ask-AI becomes a floating global component backed by logic extracted from `AskTab.jsx` (which is then deleted).

**Tech Stack:** React 18, Vite 5, Tailwind (existing tokens), lucide-react (already a dependency), Vitest + `@testing-library/react` (newly added — frontend currently has zero test infra; see Task 1).

---

## File Structure

**New files:**
| File | Responsibility |
|---|---|
| `frontend/vitest.config.js` | Vitest + jsdom config |
| `frontend/src/test/setup.js` | `@testing-library/jest-dom` matcher registration |
| `frontend/src/lib/readingProgress.js` | Pure localStorage helpers for per-book reading progress |
| `frontend/src/lib/dashboardStats.js` | Pure helpers: estimated panorama reading time, timeline teaser slice |
| `frontend/src/hooks/useReaderPrefs.js` | Font-size/theme state + localStorage persistence (lifted out of RawTextTab) |
| `frontend/src/hooks/useAskFlow.js` | Ask-history fetch + submit logic (lifted out of AskTab) |
| `frontend/src/hooks/useAnchorScrollSpy.js` | IntersectionObserver-based "which Dashboard section is visible" hook |
| `frontend/src/components/AskAI.jsx` | Global floating Ask-AI FAB + panel |
| `frontend/src/components/SettingsOverlay.jsx` | Global settings gear overlay (font/theme) |
| `frontend/src/components/stacks/StackShell.jsx` | Shared fixed full-screen chrome (back button + optional right rail) for all 5 stack pages |
| `frontend/src/components/stacks/RawTextStack.jsx` | Wraps `RawTextTab` (immersive, no rail) |
| `frontend/src/components/stacks/GraphStack.jsx` | Wraps `GraphTab` (keeps right rail) |
| `frontend/src/components/stacks/ArcsStack.jsx` | Wraps `ArcsTab` (keeps right rail) |
| `frontend/src/components/stacks/TimelineStack.jsx` | Wraps `TimelineTab` (keeps right rail) |
| `frontend/src/components/stacks/StoryStack.jsx` | Wraps `StoryTab` (immersive, no rail) |
| `frontend/src/components/dashboard/AnchorNav.jsx` | Sticky 5-pill anchor nav with scroll-spy |
| `frontend/src/components/dashboard/MiniGraphPreview.jsx` | Dependency-free SVG mini relationship graph |
| `frontend/src/components/dashboard/HeroSection.jsx` | Dashboard §1: title/hook + meta-row + ghost-link |
| `frontend/src/components/dashboard/CharactersGraphPreviewSection.jsx` | Dashboard §4: character grid + mini graph |
| `frontend/src/components/dashboard/ArcsPreviewSection.jsx` | Dashboard §5: arc cards + Story sub-link |
| `frontend/src/components/dashboard/TimelinePreviewSection.jsx` | Dashboard §6: teaser timeline |
| `frontend/src/components/dashboard/Dashboard.jsx` | Assembles all 7 Dashboard sections + bottom CTA |

**Modified files:**
| File | Change |
|---|---|
| `frontend/src/components/tabs/RawTextTab.jsx` | Accept `fontSize/theme/onStepFontSize/onToggleTheme` as props instead of local state; use `lib/readingProgress.js` instead of inline localStorage |
| `frontend/src/pages/ReaderPage.jsx` | Full rewrite: remove tab bar, add stack/ask/settings state, mount `Dashboard` + stack overlay + global `AskAI`/`SettingsOverlay`/gear button |
| `frontend/package.json` | Add `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom` devDependencies + a `test` script |

**Deleted files:**
| File | Reason |
|---|---|
| `frontend/src/components/tabs/AskTab.jsx` | Superseded by `AskAI.jsx` + `useAskFlow.js`; no longer imported anywhere once `ReaderPage.jsx` drops the tab bar |

**Explicit non-goals (per spec §1/§8, do not implement):** responsive/mobile layout, richer graph-preview visualization beyond the SVG mini-preview, a chapter-TOC replacement for the now-rail-free raw-text page, any backend/API change (confirmed no backend field exists for novel word-count — see Architecture Decision Log below).

---

## Architecture Decision Log (read before starting — resolves ambiguity the spec left open)

1. **Hero meta-row drops literal novel word-count.** The spec/mockup show "✍️约32万字" but no backend field provides this (`backend/app/models.py`'s `WorkPackage`/`LayeredSummary` have no char-count field; `ParsedBook.total_chars` in `backend/app/pipeline/parse.py` is internal-only, never exposed via any route), and this redesign is frontend-only (spec §1). Fetching every chapter's text just to sum length would defeat `RawTextTab`'s lazy-loading design. The meta-row instead shows: chapter count (`ls.chapters.length`) + an **estimated panorama-reading time** (computed client-side from already-loaded summary text length: `one_liner + story_hook + overview + arc summaries + setting card contents`, at 300 chars/minute) + reading progress (from existing localStorage).
2. **Timeline teaser = first 4 events**, not "most recent" (spec's wording is "3–5个关键/近期事件" but "recent" is undefined for a book nobody has started). Earliest events are the least spoiler-heavy honest sample.
3. **Graph preview = dependency-free inline SVG**, not an embedded `vis-network` instance (spec §8 explicitly defers this choice to implementation). Renders up to 5 main characters in a fixed pentagon layout with real edges from `getGraph`, avoiding importing the 200KB+ `vis-network` bundle on the Dashboard.
4. **The external "完整图谱 ↗" link** (`graphHtmlUrl(id)`, opens a server-rendered standalone graph page in a new tab) currently lives in `ReaderPage.jsx`'s old header. The spec never says to remove it, so it's relocated into `CharactersGraphPreviewSection.jsx`'s header as a small secondary link next to the primary in-app "查看完整图谱→" expand link.
5. **Testing scope**: frontend has zero test infrastructure today (confirmed via `AGENTS.md` and `package.json`). This plan adds a minimal Vitest + RTL setup (Task 1) and writes real unit tests **only** for new pure-logic modules with non-trivial behavior worth covering: `readingProgress.js`, `dashboardStats.js`, `useReaderPrefs.js`, `useAskFlow.js`. All presentational/composition components (Dashboard sections, stacks, `ReaderPage.jsx` itself) are verified via `npm run build` + a manual browser walkthrough (chrome-devtools MCP against real work data), matching this repo's existing convention (zero component tests exist anywhere; the earlier `RawTextTab` race-condition bug fix in this same project was itself verified via build+live-browser, not unit tests) and the design spec's own §10 prescribed verification method. `useAnchorScrollSpy.js` is excluded from unit testing (jsdom has no native `IntersectionObserver`; RawTextTab's three pre-existing `IntersectionObserver` effects have likewise never had unit tests in this codebase) — verified manually in the same walkthrough.

---

## Task 1: Add Vitest test infrastructure

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/vitest.config.js`
- Create: `frontend/src/test/setup.js`

- [ ] **Step 1: Install dependencies**

Run: `cd frontend && npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom`
Expected: packages added to `devDependencies` in `package.json`.

- [ ] **Step 2: Add the `test` script**

In `frontend/package.json`, in the `"scripts"` block (alongside existing `dev`/`build`/`preview`), add:

```json
    "test": "vitest run"
```

- [ ] **Step 3: Create the Vitest config**

Create `frontend/vitest.config.js`:

```js
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    globals: false,
  },
});
```

- [ ] **Step 4: Create the test setup file**

Create `frontend/src/test/setup.js`:

```js
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 5: Verify the harness works with a throwaway smoke test**

Create a temporary file `frontend/src/test/smoke.test.js`:

```js
import { describe, it, expect } from "vitest";

describe("smoke", () => {
  it("runs", () => {
    expect(1 + 1).toBe(2);
  });
});
```

Run: `cd frontend && npm run test`
Expected: `1 passed`. Then delete `frontend/src/test/smoke.test.js` (its only purpose was confirming the harness runs).

- [ ] **Step 6: Commit**

```bash
cd frontend && rtk git add package.json package-lock.json vitest.config.js src/test/setup.js
rtk git commit -m "chore: add Vitest + React Testing Library test infrastructure"
```

---

## Task 2: `lib/readingProgress.js`

**Files:**
- Create: `frontend/src/lib/readingProgress.js`
- Test: `frontend/src/lib/readingProgress.test.js`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/readingProgress.test.js`:

```js
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- readingProgress`
Expected: FAIL — `Cannot find module './readingProgress'` (or similar; the module doesn't exist yet).

- [ ] **Step 3: Write the implementation**

Create `frontend/src/lib/readingProgress.js`:

```js
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test -- readingProgress`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
cd frontend && rtk git add src/lib/readingProgress.js src/lib/readingProgress.test.js
rtk git commit -m "feat: add readingProgress lib module"
```

---

## Task 3: `lib/dashboardStats.js`

**Files:**
- Create: `frontend/src/lib/dashboardStats.js`
- Test: `frontend/src/lib/dashboardStats.test.js`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/dashboardStats.test.js`:

```js
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- dashboardStats`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/lib/dashboardStats.js`:

```js
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test -- dashboardStats`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
cd frontend && rtk git add src/lib/dashboardStats.js src/lib/dashboardStats.test.js
rtk git commit -m "feat: add dashboardStats lib module"
```

---

## Task 4: `hooks/useReaderPrefs.js`

**Files:**
- Create: `frontend/src/hooks/useReaderPrefs.js`
- Test: `frontend/src/hooks/useReaderPrefs.test.js`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/hooks/useReaderPrefs.test.js`:

```js
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useReaderPrefs } from "./useReaderPrefs";

beforeEach(() => {
  localStorage.clear();
});

describe("useReaderPrefs", () => {
  it("defaults to 16px / day theme when nothing is saved", () => {
    const { result } = renderHook(() => useReaderPrefs());
    expect(result.current.fontSize).toBe(16);
    expect(result.current.theme).toBe("day");
  });

  it("stepFontSize moves through the fixed size ladder and persists it", () => {
    const { result } = renderHook(() => useReaderPrefs());
    act(() => result.current.stepFontSize(1));
    expect(result.current.fontSize).toBe(18);
    expect(localStorage.getItem("novel_kg_reader_font_size")).toBe("18");
  });

  it("stepFontSize clamps at the largest size", () => {
    const { result } = renderHook(() => useReaderPrefs());
    act(() => {
      for (let i = 0; i < 10; i++) result.current.stepFontSize(1);
    });
    expect(result.current.fontSize).toBe(22);
  });

  it("stepFontSize clamps at the smallest size", () => {
    const { result } = renderHook(() => useReaderPrefs());
    act(() => {
      for (let i = 0; i < 10; i++) result.current.stepFontSize(-1);
    });
    expect(result.current.fontSize).toBe(14);
  });

  it("toggleTheme flips between day and night and persists it", () => {
    const { result } = renderHook(() => useReaderPrefs());
    act(() => result.current.toggleTheme());
    expect(result.current.theme).toBe("night");
    expect(localStorage.getItem("novel_kg_reader_theme")).toBe("night");
    act(() => result.current.toggleTheme());
    expect(result.current.theme).toBe("day");
  });

  it("reads a previously saved font size on mount", () => {
    localStorage.setItem("novel_kg_reader_font_size", "20");
    const { result } = renderHook(() => useReaderPrefs());
    expect(result.current.fontSize).toBe(20);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- useReaderPrefs`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/hooks/useReaderPrefs.js`:

```js
import { useEffect, useState, useCallback } from "react";

const FONT_SIZES = [14, 16, 18, 20, 22];
const FONT_SIZE_KEY = "novel_kg_reader_font_size";
const THEME_KEY = "novel_kg_reader_theme";

// App-wide reading preferences (font size + day/night theme). These used to
// live only inside RawTextTab as local state; the Dashboard redesign needs
// the same two prefs controllable from a global settings gear icon that's
// visible on every screen (design spec §2), so this hook lifts them out
// into a shared place. Storage keys are unchanged, so any prefs a user
// already saved before this refactor keep working.
export function useReaderPrefs() {
  const [fontSize, setFontSize] = useState(
    () => Number(localStorage.getItem(FONT_SIZE_KEY)) || 16
  );
  const [theme, setTheme] = useState(() => localStorage.getItem(THEME_KEY) || "day");

  useEffect(() => {
    localStorage.setItem(FONT_SIZE_KEY, String(fontSize));
  }, [fontSize]);

  useEffect(() => {
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  const stepFontSize = useCallback((delta) => {
    setFontSize((cur) => {
      const idx = FONT_SIZES.indexOf(cur);
      const nextIdx = Math.min(FONT_SIZES.length - 1, Math.max(0, (idx === -1 ? 1 : idx) + delta));
      return FONT_SIZES[nextIdx];
    });
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((t) => (t === "night" ? "day" : "night"));
  }, []);

  return { fontSize, theme, stepFontSize, toggleTheme };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test -- useReaderPrefs`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
cd frontend && rtk git add src/hooks/useReaderPrefs.js src/hooks/useReaderPrefs.test.js
rtk git commit -m "feat: add useReaderPrefs hook"
```

---

## Task 5: Refactor `RawTextTab.jsx` to use `readingProgress.js` and accept prefs as props

**Files:**
- Modify: `frontend/src/components/tabs/RawTextTab.jsx`

- [ ] **Step 1: Update the function signature and imports**

Find:
```jsx
export default function RawTextTab({ id, ls, jump, setRight, onAskAboutSelection }) {
```

Replace with:
```jsx
export default function RawTextTab({
  id,
  ls,
  jump,
  setRight,
  onAskAboutSelection,
  fontSize,
  theme,
  onStepFontSize,
  onToggleTheme,
}) {
```

Add near the top of the file's import block:
```jsx
import { getReadingProgress, setReadingProgress } from "../../lib/readingProgress";
```

- [ ] **Step 2: Delete the local font-size/theme state and its persistence effects**

Find and delete these lines entirely:
```jsx
  const [fontSize, setFontSize] = useState(() => Number(localStorage.getItem("novel_kg_reader_font_size")) || 16);
  const [theme, setTheme] = useState(() => localStorage.getItem("novel_kg_reader_theme") || "day");

  useEffect(() => { localStorage.setItem("novel_kg_reader_font_size", String(fontSize)); }, [fontSize]);
  useEffect(() => { localStorage.setItem("novel_kg_reader_theme", theme); }, [theme]);

  const FONT_SIZES = [14, 16, 18, 20, 22];
  function stepFontSize(delta) {
    setFontSize((cur) => {
      const idx = FONT_SIZES.indexOf(cur);
      const nextIdx = Math.min(FONT_SIZES.length - 1, Math.max(0, (idx === -1 ? 1 : idx) + delta));
      return FONT_SIZES[nextIdx];
    });
  }
```
(`fontSize` and `theme` are now props, supplied by the caller via `useReaderPrefs()`.)

- [ ] **Step 3: Update the toolbar buttons to call the new prop callbacks**

Find:
```jsx
        <div className="mb-4 flex items-center gap-3 text-sm">
          <button type="button" onClick={() => stepFontSize(-1)} className="rounded border px-2 py-1">A-</button>
          <button type="button" onClick={() => stepFontSize(1)} className="rounded border px-2 py-1">A+</button>
          <button type="button" onClick={() => setTheme((t) => (t === "night" ? "day" : "night"))} className="rounded border px-2 py-1">
            {theme === "night" ? "☀️ 日间" : "🌙 夜间"}
          </button>
        </div>
```

Replace with:
```jsx
        <div className="mb-4 flex items-center gap-3 text-sm">
          <button type="button" onClick={() => onStepFontSize(-1)} className="rounded border px-2 py-1">A-</button>
          <button type="button" onClick={() => onStepFontSize(1)} className="rounded border px-2 py-1">A+</button>
          <button type="button" onClick={onToggleTheme} className="rounded border px-2 py-1">
            {theme === "night" ? "☀️ 日间" : "🌙 夜间"}
          </button>
        </div>
```

- [ ] **Step 4: Replace the progress-writing code inside the paragraph IntersectionObserver effect**

Find:
```jsx
        const { chapter, para } = topEl.dataset;
        if (chapter && para !== undefined) {
          localStorage.setItem(progressKey, JSON.stringify({ chapterId: chapter, paragraphIndex: Number(para) }));
        }
```

Replace with:
```jsx
        const { chapter, para } = topEl.dataset;
        if (chapter && para !== undefined) {
          setReadingProgress(id, chapter, Number(para));
        }
```

Find the `progressKey` declaration near the top of the component:
```jsx
  const progressKey = `novel_kg_reader_progress_${id}`;
```
Delete this line entirely (no longer needed — `id` is used directly now).

Find that same effect's dependency array (the one containing `progressKey`), e.g.:
```jsx
  }, [chapterState, progressKey]);
```
Replace with:
```jsx
  }, [chapterState, id]);
```

- [ ] **Step 5: Replace the restore-on-mount effect body**

Find:
```jsx
    if (restoredRef.current === progressKey) return;
    restoredRef.current = progressKey;
    if (jump && jump.nonce !== lastHandledNonceRef.current) return;
    const saved = localStorage.getItem(progressKey);
    if (!saved) return;
    try {
      const { chapterId, paragraphIndex } = JSON.parse(saved);
      loadChapter(chapterId).then(() => {
        setTimeout(() => {
          document.getElementById(`p-${chapterId}-${paragraphIndex}`)?.scrollIntoView({ block: "start" });
        }, 50);
      });
    } catch {
      localStorage.removeItem(progressKey);
    }
  }, [progressKey, loadChapter, jump]);
```

Replace with:
```jsx
    if (restoredRef.current === id) return;
    restoredRef.current = id;
    if (jump && jump.nonce !== lastHandledNonceRef.current) return;
    const saved = getReadingProgress(id);
    if (!saved) return;
    const { chapterId, paragraphIndex } = saved;
    loadChapter(chapterId).then(() => {
      setTimeout(() => {
        document.getElementById(`p-${chapterId}-${paragraphIndex}`)?.scrollIntoView({ block: "start" });
      }, 50);
    });
  }, [id, loadChapter, jump]);
```

- [ ] **Step 6: Verify with a clean build**

Run: `cd frontend && npm run build`
Expected: clean build, no errors (this is a behavior-preserving refactor with no new automated test — RawTextTab has no existing component tests, and its behavior is instead verified manually in Task 16's browser walkthrough after `RawTextStack.jsx` exists to actually render it with real props).

- [ ] **Step 7: Commit**

```bash
cd frontend && rtk git add src/components/tabs/RawTextTab.jsx
rtk git commit -m "refactor: lift font/theme prefs and reading-progress storage out of RawTextTab"
```

---

## Task 6: `hooks/useAskFlow.js`

**Files:**
- Create: `frontend/src/hooks/useAskFlow.js`
- Test: `frontend/src/hooks/useAskFlow.test.js`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/hooks/useAskFlow.test.js`:

```js
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useAskFlow } from "./useAskFlow";
import * as api from "../api";

vi.mock("../api");

beforeEach(() => {
  vi.resetAllMocks();
});

describe("useAskFlow", () => {
  it("loads history on mount", async () => {
    api.getAskHistory.mockResolvedValue({ history: [{ question: "q1", answer: "a1", cited: [] }] });
    const { result } = renderHook(() => useAskFlow("w1"));
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.history).toEqual([{ question: "q1", answer: "a1", cited: [] }]);
  });

  it("runAsk appends a new entry to history on success", async () => {
    api.getAskHistory.mockResolvedValue({ history: [] });
    api.askQuestion.mockResolvedValue({ answer: "a2", cited: ["角色A"] });
    const { result } = renderHook(() => useAskFlow("w1"));
    await waitFor(() => expect(result.current.loaded).toBe(true));
    await act(async () => {
      await result.current.runAsk("q2");
    });
    expect(result.current.history).toEqual([{ question: "q2", answer: "a2", cited: ["角色A"] }]);
    expect(result.current.loading).toBe(false);
  });

  it("runAsk sets an error message on failure and does not touch history", async () => {
    api.getAskHistory.mockResolvedValue({ history: [] });
    api.askQuestion.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useAskFlow("w1"));
    await waitFor(() => expect(result.current.loaded).toBe(true));
    await act(async () => {
      await result.current.runAsk("q3");
    });
    expect(result.current.error).toBe("boom");
    expect(result.current.history).toEqual([]);
  });

  it("runAsk ignores empty/whitespace-only questions", async () => {
    api.getAskHistory.mockResolvedValue({ history: [] });
    const { result } = renderHook(() => useAskFlow("w1"));
    await waitFor(() => expect(result.current.loaded).toBe(true));
    await act(async () => {
      await result.current.runAsk("   ");
    });
    expect(api.askQuestion).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- useAskFlow`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/hooks/useAskFlow.js`:

```js
import { useEffect, useState } from "react";
import { getAskHistory, askQuestion } from "../api";

// Data-fetching core of the "Ask AI about this book" feature: loads past
// Q&A history once, and exposes runAsk(question) to submit a new one. Used
// by the global floating AskAI panel (design spec §2) — extracted out of
// the old AskTab.jsx so the same logic can back a floating panel instead of
// a full tab page.
export function useAskFlow(id) {
  const [history, setHistory] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    getAskHistory(id)
      .then((r) => {
        if (!cancelled) setHistory(r.history || []);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function runAsk(questionText) {
    const question = (questionText || "").trim();
    if (!question || loading) return null;
    setLoading(true);
    setError("");
    try {
      const res = await askQuestion(id, question);
      const entry = { question, answer: res.answer, cited: res.cited || [] };
      setHistory((h) => [...h, entry]);
      return entry;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setLoading(false);
    }
  }

  return { history, loaded, loading, error, runAsk };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test -- useAskFlow`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
cd frontend && rtk git add src/hooks/useAskFlow.js src/hooks/useAskFlow.test.js
rtk git commit -m "feat: add useAskFlow hook"
```

---

## Task 7: `components/AskAI.jsx`

**Files:**
- Create: `frontend/src/components/AskAI.jsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/AskAI.jsx`:

```jsx
import { useEffect, useRef, useState } from "react";
import { MessageCircle, X } from "lucide-react";
import { useAskFlow } from "../hooks/useAskFlow";

// Global floating "Ask AI" entry point (design spec §2): replaces the old
// dedicated 问答 tab. Mounted once at the ReaderPage level so it floats on
// top of both the Dashboard and every full-screen stack sub-page.
export default function AskAI({ id, open, onOpenChange, seed }) {
  const { history, loaded, loading, error, runAsk } = useAskFlow(id);
  const [q, setQ] = useState("");
  const lastHandledNonceRef = useRef(null);

  useEffect(() => {
    if (!seed || seed.nonce === lastHandledNonceRef.current) return;
    lastHandledNonceRef.current = seed.nonce;
    onOpenChange(true);
    if (seed.autoSubmit === false) {
      setQ(seed.question);
    } else {
      runAsk(seed.question);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed]);

  async function submit(e) {
    e.preventDefault();
    if (!q.trim()) return;
    await runAsk(q);
    setQ("");
  }

  return (
    <>
      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2 rounded-full bg-ink-900 px-4 py-3 text-sm text-white shadow-pop hover:bg-ink-900/90"
      >
        <MessageCircle size={16} strokeWidth={1.5} />
        问AI
      </button>
      {open && (
        <div className="fixed bottom-24 right-6 z-50 flex max-h-[70vh] w-[340px] flex-col rounded-card border border-ink-300 bg-white shadow-pop">
          <div className="flex items-center justify-between border-b border-ink-300 px-4 py-3">
            <h3 className="font-serif text-sm font-semibold text-ink-900">问AI</h3>
            <button type="button" onClick={() => onOpenChange(false)} aria-label="关闭">
              <X size={16} strokeWidth={1.5} className="text-ink-600" />
            </button>
          </div>
          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {loaded && history.length === 0 && !loading && (
              <p className="text-sm text-ink-600">还没有问答记录，试着问一个问题吧。</p>
            )}
            {[...history].reverse().map((item, i) => (
              <div key={i} className="rounded-card border border-ink-300 bg-paper-50 p-3">
                <p className="text-sm font-medium text-ink-900">Q：{item.question}</p>
                <p className="mt-1 whitespace-pre-wrap text-sm text-ink-900">{item.answer}</p>
              </div>
            ))}
          </div>
          {error && <div className="px-4 pb-2 text-sm text-danger-600">{error}</div>}
          <form onSubmit={submit} className="flex gap-2 border-t border-ink-300 p-3">
            <input
              className="flex-1 rounded-btn border border-ink-300 px-3 py-2 text-sm"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="输入问题…"
              disabled={loading}
            />
            <button
              type="submit"
              className="rounded-btn bg-seal-600 px-3 py-2 text-sm text-white hover:bg-seal-700 disabled:opacity-50"
              disabled={loading || !q.trim()}
            >
              {loading ? "…" : "问"}
            </button>
          </form>
        </div>
      )}
    </>
  );
}
```

- [ ] **Step 2: Verify the app still builds**

Run: `cd frontend && npm run build`
Expected: clean build (this component isn't wired into any page yet — Task 15 does that — so this step just confirms it's syntactically valid and its imports resolve).

- [ ] **Step 3: Commit**

```bash
cd frontend && rtk git add src/components/AskAI.jsx
rtk git commit -m "feat: add global floating AskAI component"
```

---

## Task 8: `components/SettingsOverlay.jsx`

**Files:**
- Create: `frontend/src/components/SettingsOverlay.jsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/SettingsOverlay.jsx`:

```jsx
import { X } from "lucide-react";

// Global settings gear panel (design spec §2): app-wide reading
// preferences (font size, day/night theme). Distinct from a book's own
// 世界观设定 content (SettingsTab), which stays a normal Dashboard section.
export default function SettingsOverlay({ open, onClose, prefs }) {
  if (!open) return null;
  const { fontSize, theme, stepFontSize, toggleTheme } = prefs;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/30" onClick={onClose}>
      <div
        className="w-[320px] rounded-card border border-ink-300 bg-white p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="font-serif text-base font-semibold text-ink-900">阅读设置</h3>
          <button type="button" onClick={onClose} aria-label="关闭">
            <X size={16} strokeWidth={1.5} className="text-ink-600" />
          </button>
        </div>
        <div className="mt-4">
          <p className="text-xs font-semibold uppercase text-ink-600">字号</p>
          <div className="mt-2 flex items-center gap-2">
            <button type="button" onClick={() => stepFontSize(-1)} className="rounded border border-ink-300 px-3 py-1.5 text-sm">A-</button>
            <span className="text-sm text-ink-900">{fontSize}px</span>
            <button type="button" onClick={() => stepFontSize(1)} className="rounded border border-ink-300 px-3 py-1.5 text-sm">A+</button>
          </div>
        </div>
        <div className="mt-4">
          <p className="text-xs font-semibold uppercase text-ink-600">主题</p>
          <button
            type="button"
            onClick={toggleTheme}
            className="mt-2 rounded border border-ink-300 px-3 py-1.5 text-sm"
          >
            {theme === "night" ? "☀️ 切换为日间" : "🌙 切换为夜间"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify the app still builds**

Run: `cd frontend && npm run build`
Expected: clean build.

- [ ] **Step 3: Commit**

```bash
cd frontend && rtk git add src/components/SettingsOverlay.jsx
rtk git commit -m "feat: add global SettingsOverlay component"
```

---

## Task 9: `hooks/useAnchorScrollSpy.js` + `components/dashboard/AnchorNav.jsx`

**Files:**
- Create: `frontend/src/hooks/useAnchorScrollSpy.js`
- Create: `frontend/src/components/dashboard/AnchorNav.jsx`

- [ ] **Step 1: Write the scroll-spy hook**

Create `frontend/src/hooks/useAnchorScrollSpy.js`:

```js
import { useEffect, useState } from "react";

// Highlights whichever Dashboard section is currently in view as the user
// scrolls, so the sticky anchor-nav pill row (design spec §2) stays in
// sync without requiring a pill click. Mirrors the verified interaction
// pattern from docs/superpowers/specs/2026-08-22-reader-dashboard-mockup.html.
// Not unit-tested: jsdom has no native IntersectionObserver, and this
// codebase has never unit-tested its other IntersectionObserver-based
// effects (see RawTextTab.jsx) either — verified manually instead.
export function useAnchorScrollSpy(sectionIds) {
  const [activeId, setActiveId] = useState(sectionIds[0]);

  useEffect(() => {
    const elements = sectionIds.map((sid) => document.getElementById(sid)).filter(Boolean);
    if (elements.length === 0) return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveId(entry.target.id);
          }
        }
      },
      { rootMargin: "-40% 0px -50% 0px" }
    );
    for (const el of elements) observer.observe(el);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sectionIds.join(",")]);

  return activeId;
}
```

- [ ] **Step 2: Write the AnchorNav component**

Create `frontend/src/components/dashboard/AnchorNav.jsx`:

```jsx
import { useAnchorScrollSpy } from "../../hooks/useAnchorScrollSpy";

const SECTIONS = [
  { id: "sec-hero", label: "简介" },
  { id: "sec-characters", label: "人物" },
  { id: "sec-arcs", label: "情节" },
  { id: "sec-timeline", label: "时间" },
  { id: "sec-settings", label: "设定" },
];

export default function AnchorNav() {
  const activeId = useAnchorScrollSpy(SECTIONS.map((s) => s.id));

  function jumpTo(id) {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <nav className="sticky top-0 z-10 -mx-8 flex gap-2 overflow-x-auto border-b border-ink-300 bg-paper-50/95 px-8 py-2 backdrop-blur">
      {SECTIONS.map((s) => (
        <button
          key={s.id}
          type="button"
          onClick={() => jumpTo(s.id)}
          className={
            "shrink-0 rounded-full px-3 py-1 text-xs transition-colors " +
            (activeId === s.id
              ? "bg-ink-900 text-white"
              : "border border-ink-300 text-ink-600 hover:border-seal-600 hover:text-seal-600")
          }
        >
          {s.label}
        </button>
      ))}
    </nav>
  );
}
```

- [ ] **Step 3: Verify the app still builds**

Run: `cd frontend && npm run build`
Expected: clean build.

- [ ] **Step 4: Commit**

```bash
cd frontend && rtk git add src/hooks/useAnchorScrollSpy.js src/components/dashboard/AnchorNav.jsx
rtk git commit -m "feat: add anchor-nav scroll-spy hook and component"
```

---

## Task 10: `components/dashboard/MiniGraphPreview.jsx`

**Files:**
- Create: `frontend/src/components/dashboard/MiniGraphPreview.jsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/dashboard/MiniGraphPreview.jsx`:

```jsx
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
```

- [ ] **Step 2: Verify the app still builds**

Run: `cd frontend && npm run build`
Expected: clean build. (Not unit-tested — this is a small presentational SVG component with no branching logic of the kind covered by this plan's Task-1 testing-scope decision; it's exercised visually in Task 16's browser walkthrough.)

- [ ] **Step 3: Commit**

```bash
cd frontend && rtk git add src/components/dashboard/MiniGraphPreview.jsx
rtk git commit -m "feat: add dependency-free MiniGraphPreview component"
```

---

## Task 11: `components/dashboard/HeroSection.jsx`

**Files:**
- Create: `frontend/src/components/dashboard/HeroSection.jsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/dashboard/HeroSection.jsx`:

```jsx
import { estimatePanoramaMinutes } from "../../lib/dashboardStats";
import { describeProgress } from "../../lib/readingProgress";

export default function HeroSection({ id, pkg, ls, onStartReading }) {
  const chapters = ls.chapters || [];
  const minutes = estimatePanoramaMinutes(pkg, ls);
  const progress = describeProgress(id, chapters);

  return (
    <section id="sec-hero" className="scroll-mt-16 border-b border-ink-300 pb-8">
      <p className="text-xs uppercase tracking-wide text-ink-600">30分钟读懂一本书</p>
      <h1 className="mt-1 font-serif text-2xl text-ink-900">{pkg.title}</h1>
      {ls.one_liner && <p className="mt-3 font-serif text-lg font-semibold text-ink-900">{ls.one_liner}</p>}
      {ls.story_hook && <p className="mt-2 text-ink-600">{ls.story_hook}</p>}

      <div className="mt-4 flex flex-wrap gap-4 rounded-card border border-ink-300 bg-paper-100 px-4 py-2 text-xs text-ink-600">
        {chapters.length > 0 && (
          <span>
            📖 共 <b className="text-ink-900">{chapters.length}</b> 章
          </span>
        )}
        <span>
          ⏱ 全景阅读约 <b className="text-ink-900">{minutes}</b> 分钟
        </span>
        {progress && (
          <span>
            🔖 原文已读 <b className="text-ink-900">{progress.percent}%</b>（{progress.chapterTitle}）
          </span>
        )}
      </div>

      <button
        type="button"
        onClick={onStartReading}
        className="mt-4 text-sm text-ink-600 underline decoration-dotted hover:text-seal-600"
      >
        不看全景，直接读原文 →
      </button>
    </section>
  );
}
```

- [ ] **Step 2: Verify the app still builds**

Run: `cd frontend && npm run build`
Expected: clean build.

- [ ] **Step 3: Commit**

```bash
cd frontend && rtk git add src/components/dashboard/HeroSection.jsx
rtk git commit -m "feat: add Dashboard HeroSection component"
```

---

## Task 12: `components/dashboard/CharactersGraphPreviewSection.jsx`

**Files:**
- Create: `frontend/src/components/dashboard/CharactersGraphPreviewSection.jsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/dashboard/CharactersGraphPreviewSection.jsx`:

```jsx
import { useEffect, useState } from "react";
import { getGraph, graphHtmlUrl } from "../../api";
import MiniGraphPreview from "./MiniGraphPreview";

export default function CharactersGraphPreviewSection({ id, pkg, onOpenGraph }) {
  const [graph, setGraph] = useState(null);
  const mains = pkg.main_characters || [];

  useEffect(() => {
    let cancelled = false;
    getGraph(id)
      .then((g) => {
        if (!cancelled) setGraph(g);
      })
      .catch(() => {
        if (!cancelled) setGraph(null);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <section id="sec-characters" className="scroll-mt-16 border-b border-ink-300 py-8">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-lg font-semibold text-ink-900">人物关系</h2>
        <div className="flex items-center gap-3 text-sm">
          <a
            href={graphHtmlUrl(id)}
            target="_blank"
            rel="noreferrer"
            className="text-ink-600 hover:text-seal-600 hover:underline"
          >
            在新标签页打开 ↗
          </a>
          <button type="button" onClick={onOpenGraph} className="text-ink-600 hover:text-seal-600 hover:underline">
            查看完整图谱→
          </button>
        </div>
      </div>
      {mains.length === 0 ? (
        <p className="mt-4 text-ink-600">未识别到主要人物</p>
      ) : (
        <div className="mt-4 grid grid-cols-2 gap-4">
          {mains.map((c) => (
            <div key={c.id} className="rounded-card border border-ink-300 bg-white p-4">
              <div className="font-medium text-ink-900">{c.label}</div>
              {c.description && <div className="mt-1 line-clamp-2 text-sm text-ink-600">{c.description}</div>}
              <div className="mt-2 text-xs text-ink-600">提及 {c.mention_count} 次</div>
            </div>
          ))}
        </div>
      )}
      <div className="mt-4 rounded-card border border-dashed border-ink-300 p-3">
        <MiniGraphPreview mainCharacters={mains} graph={graph} />
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Verify the app still builds**

Run: `cd frontend && npm run build`
Expected: clean build.

- [ ] **Step 3: Commit**

```bash
cd frontend && rtk git add src/components/dashboard/CharactersGraphPreviewSection.jsx
rtk git commit -m "feat: add Dashboard CharactersGraphPreviewSection component"
```

---

## Task 13: `components/dashboard/ArcsPreviewSection.jsx` + `TimelinePreviewSection.jsx`

**Files:**
- Create: `frontend/src/components/dashboard/ArcsPreviewSection.jsx`
- Create: `frontend/src/components/dashboard/TimelinePreviewSection.jsx`

- [ ] **Step 1: Write ArcsPreviewSection**

Create `frontend/src/components/dashboard/ArcsPreviewSection.jsx`:

```jsx
export default function ArcsPreviewSection({ ls, onOpenArcs, onOpenStory }) {
  const arcs = ls.arcs || [];
  return (
    <section id="sec-arcs" className="scroll-mt-16 border-b border-ink-300 py-8">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-lg font-semibold text-ink-900">情节脉络</h2>
        <button type="button" onClick={onOpenArcs} className="text-sm text-ink-600 hover:text-seal-600 hover:underline">
          查看完整→
        </button>
      </div>
      {arcs.length === 0 ? (
        <p className="mt-4 text-ink-600">未识别到情节线</p>
      ) : (
        <div className="mt-4 space-y-3">
          {arcs.map((a, i) => (
            <div key={i} className="rounded-card border border-ink-300 bg-white p-4">
              <div className="font-serif font-semibold text-ink-900">{a.title}</div>
              <p className="mt-1 text-sm leading-relaxed text-ink-900">{a.summary}</p>
              {a.member_characters?.length > 0 && (
                <p className="mt-2 text-xs text-ink-600">涉及人物：{a.member_characters.join("、")}</p>
              )}
            </div>
          ))}
        </div>
      )}
      <button
        type="button"
        onClick={onOpenStory}
        className="mt-3 text-sm text-ink-600 hover:text-seal-600 hover:underline"
      >
        查看逐幕剧情正片 →
      </button>
    </section>
  );
}
```

- [ ] **Step 2: Write TimelinePreviewSection**

Create `frontend/src/components/dashboard/TimelinePreviewSection.jsx`:

```jsx
import { useEffect, useState } from "react";
import { getTimeline } from "../../api";
import { pickTimelineTeaser } from "../../lib/dashboardStats";

export default function TimelinePreviewSection({ id, onOpenTimeline }) {
  const [events, setEvents] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getTimeline(id)
      .then((r) => {
        if (!cancelled) setEvents(r.events || []);
      })
      .catch(() => {
        if (!cancelled) setEvents([]);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const teaser = pickTimelineTeaser(events, 4);

  return (
    <section id="sec-timeline" className="scroll-mt-16 border-b border-ink-300 py-8">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-lg font-semibold text-ink-900">时间轴</h2>
        <button type="button" onClick={onOpenTimeline} className="text-sm text-ink-600 hover:text-seal-600 hover:underline">
          查看完整→
        </button>
      </div>
      {events === null && <p className="mt-4 text-ink-600">加载中…</p>}
      {events?.length === 0 && <p className="mt-4 text-ink-600">未生成任何情节事件</p>}
      {teaser.length > 0 && (
        <div className="relative mt-4 border-l-2 border-ink-300 pl-6">
          {teaser.map((e) => (
            <div key={e.seq} className="relative mb-4">
              <span
                aria-hidden="true"
                className="absolute -left-[29px] top-1 h-3 w-3 rounded-full border-2 border-paper-50 bg-seal-600"
              />
              <p className="text-xs font-semibold text-ink-600">{e.chapter_title}</p>
              <p className="mt-1 text-sm text-ink-900">{e.summary}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 3: Verify the app still builds**

Run: `cd frontend && npm run build`
Expected: clean build.

- [ ] **Step 4: Commit**

```bash
cd frontend && rtk git add src/components/dashboard/ArcsPreviewSection.jsx src/components/dashboard/TimelinePreviewSection.jsx
rtk git commit -m "feat: add Dashboard ArcsPreviewSection and TimelinePreviewSection components"
```

---

## Task 14: `components/dashboard/Dashboard.jsx`

**Files:**
- Create: `frontend/src/components/dashboard/Dashboard.jsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/dashboard/Dashboard.jsx`:

```jsx
import SuggestedQuestions from "../SuggestedQuestions";
import SettingsTab from "../tabs/SettingsTab";
import AnchorNav from "./AnchorNav";
import HeroSection from "./HeroSection";
import ArcsPreviewSection from "./ArcsPreviewSection";
import TimelinePreviewSection from "./TimelinePreviewSection";
import CharactersGraphPreviewSection from "./CharactersGraphPreviewSection";

const noop = () => {};

export default function Dashboard({ id, pkg, ls, onAsk, onOpenStack }) {
  const questions = pkg.suggested_questions || [];

  return (
    <div className="mx-auto max-w-3xl px-8 py-8">
      <AnchorNav />

      <HeroSection id={id} pkg={pkg} ls={ls} onStartReading={() => onOpenStack("raw")} />

      <section className="border-b border-ink-300 py-8">
        <h2 className="font-serif text-lg font-semibold text-ink-900">内容简介</h2>
        {ls.overview ? (
          <p className="mt-3 leading-relaxed text-ink-900">{ls.overview}</p>
        ) : (
          <p className="mt-3 text-ink-600">暂无总览内容。</p>
        )}
      </section>

      <section className="border-b border-ink-300 py-8">
        <SuggestedQuestions questions={questions} onAsk={onAsk} />
      </section>

      <CharactersGraphPreviewSection id={id} pkg={pkg} onOpenGraph={() => onOpenStack("graph")} />

      <ArcsPreviewSection
        ls={ls}
        onOpenArcs={() => onOpenStack("arcs")}
        onOpenStory={() => onOpenStack("story")}
      />

      <TimelinePreviewSection id={id} onOpenTimeline={() => onOpenStack("timeline")} />

      <section id="sec-settings" className="scroll-mt-16 py-8">
        <h2 className="mb-4 font-serif text-lg font-semibold text-ink-900">世界观设定</h2>
        <SettingsTab cards={pkg.setting_cards || []} setRight={noop} />
      </section>

      <div className="mt-4 rounded-card border border-dashed border-ink-300 py-8 text-center">
        <p className="text-ink-900">全景看完了？带着这些人物和线索，去读原文会更有感觉。</p>
        <button
          type="button"
          onClick={() => onOpenStack("raw")}
          className="mt-4 rounded-btn bg-seal-600 px-6 py-3 text-base text-white hover:bg-seal-700"
        >
          开始阅读原文 →
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify the app still builds**

Run: `cd frontend && npm run build`
Expected: clean build.

- [ ] **Step 3: Commit**

```bash
cd frontend && rtk git add src/components/dashboard/Dashboard.jsx
rtk git commit -m "feat: add Dashboard root component"
```

---

## Task 15: `components/stacks/StackShell.jsx` + the 5 stack wrapper components

**Files:**
- Create: `frontend/src/components/stacks/StackShell.jsx`
- Create: `frontend/src/components/stacks/RawTextStack.jsx`
- Create: `frontend/src/components/stacks/GraphStack.jsx`
- Create: `frontend/src/components/stacks/ArcsStack.jsx`
- Create: `frontend/src/components/stacks/TimelineStack.jsx`
- Create: `frontend/src/components/stacks/StoryStack.jsx`

- [ ] **Step 1: Write StackShell**

Create `frontend/src/components/stacks/StackShell.jsx`:

```jsx
import { ArrowLeft } from "lucide-react";

// Full-screen "stack sub-page" chrome shared by all 5 deep-dive pages
// (design spec §4): a fixed overlay that covers the entire viewport
// (including AppShell's left bookshelf), a "← 返回" header, and an optional
// right detail rail for pages that still use the AppShell `setRight`
// pattern (design spec §5). `right == null` renders a single, wider column
// instead — used by the 原文/剧情正片 stack pages for true immersion.
export default function StackShell({ title, onBack, right, children }) {
  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-paper-50">
      <header className="flex items-center gap-3 border-b border-ink-300 bg-paper-100 px-6 py-3">
        <button type="button" onClick={onBack} className="flex items-center gap-1 text-sm text-ink-600 hover:text-seal-600">
          <ArrowLeft size={16} strokeWidth={1.5} />
          返回
        </button>
        <h1 className="font-serif text-base font-semibold text-ink-900">{title}</h1>
      </header>
      {right != null ? (
        <div className="flex flex-1 overflow-hidden">
          <main className="flex-1 overflow-y-auto">{children}</main>
          <aside className="w-[200px] shrink-0 overflow-y-auto border-l border-ink-300 bg-paper-100 p-3">
            {right}
          </aside>
        </div>
      ) : (
        <main className="flex-1 overflow-y-auto">{children}</main>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Write RawTextStack (immersive, no rail)**

Create `frontend/src/components/stacks/RawTextStack.jsx`:

```jsx
import { useState } from "react";
import RawTextTab from "../tabs/RawTextTab";
import StackShell from "./StackShell";
import { describeProgress } from "../../lib/readingProgress";

// Immersive/rail-free: RawTextTab still calls setRight internally (its
// chapter-TOC effect), but StackShell is rendered without a `right` prop
// here, so that content is simply never displayed — this is what lets
// RawTextTab stay completely unmodified w.r.t. its setRight usage while
// still achieving "沉浸阅读 · 无侧栏" (design spec §5).
export default function RawTextStack({ id, ls, jump, onBack, onAskAboutSelection, prefs }) {
  const [, setRight] = useState(null);
  const progress = describeProgress(id, ls.chapters || []);

  return (
    <StackShell title="原文" onBack={onBack}>
      <div className="mx-auto max-w-2xl px-8 py-6">
        <div className="mb-4 flex items-center gap-3 text-xs">
          <span className="rounded-full bg-seal-100 px-2 py-0.5 text-seal-700">沉浸阅读 · 无侧栏</span>
          {progress && (
            <span className="flex-1 text-ink-600">
              阅读进度：{progress.chapterTitle} / 共 {(ls.chapters || []).length} 章
              <span className="ml-2 inline-block h-1 w-24 rounded-full bg-ink-300 align-middle">
                <span
                  className="block h-1 rounded-full bg-seal-600"
                  style={{ width: `${progress.percent}%` }}
                />
              </span>
            </span>
          )}
        </div>
        <RawTextTab
          id={id}
          ls={ls}
          jump={jump}
          setRight={setRight}
          onAskAboutSelection={onAskAboutSelection}
          fontSize={prefs.fontSize}
          theme={prefs.theme}
          onStepFontSize={prefs.stepFontSize}
          onToggleTheme={prefs.toggleTheme}
        />
      </div>
    </StackShell>
  );
}
```

- [ ] **Step 3: Write GraphStack, ArcsStack, TimelineStack (each keeps the right rail)**

Create `frontend/src/components/stacks/GraphStack.jsx`:

```jsx
import { useState } from "react";
import GraphTab from "../tabs/GraphTab";
import StackShell from "./StackShell";

export default function GraphStack({ id, onBack, onViewChapter }) {
  const [right, setRight] = useState(null);
  return (
    <StackShell title="完整人物关系图谱" onBack={onBack} right={right}>
      <div className="px-6 py-4">
        <GraphTab id={id} setRight={setRight} onViewChapter={onViewChapter} />
      </div>
    </StackShell>
  );
}
```

Create `frontend/src/components/stacks/ArcsStack.jsx`:

```jsx
import { useState } from "react";
import ArcsTab from "../tabs/ArcsTab";
import StackShell from "./StackShell";

export default function ArcsStack({ id, ls, onBack }) {
  const [right, setRight] = useState(null);
  return (
    <StackShell title="完整情节脉络" onBack={onBack} right={right}>
      <div className="px-6 py-4">
        <ArcsTab id={id} ls={ls} setRight={setRight} />
      </div>
    </StackShell>
  );
}
```

Create `frontend/src/components/stacks/TimelineStack.jsx`:

```jsx
import { useState } from "react";
import TimelineTab from "../tabs/TimelineTab";
import StackShell from "./StackShell";

export default function TimelineStack({ id, onBack, onViewChapter }) {
  const [right, setRight] = useState(null);
  return (
    <StackShell title="完整时间轴" onBack={onBack} right={right}>
      <div className="px-6 py-4">
        <TimelineTab id={id} setRight={setRight} onViewChapter={onViewChapter} />
      </div>
    </StackShell>
  );
}
```

- [ ] **Step 4: Write StoryStack (immersive, no rail — StoryTab never uses the right sidebar anyway)**

Create `frontend/src/components/stacks/StoryStack.jsx`:

```jsx
import { useState } from "react";
import StoryTab from "../tabs/StoryTab";
import StackShell from "./StackShell";

export default function StoryStack({ id, onBack }) {
  const [, setRight] = useState(null);
  return (
    <StackShell title="剧情正片" onBack={onBack}>
      <div className="px-6 py-4">
        <StoryTab id={id} setRight={setRight} />
      </div>
    </StackShell>
  );
}
```

- [ ] **Step 5: Verify the app still builds**

Run: `cd frontend && npm run build`
Expected: clean build.

- [ ] **Step 6: Commit**

```bash
cd frontend && rtk git add src/components/stacks/
rtk git commit -m "feat: add StackShell and the 5 stack wrapper components"
```

---

## Task 16: Rewrite `ReaderPage.jsx`, delete `AskTab.jsx`, and run the full manual verification pass

**Files:**
- Modify: `frontend/src/pages/ReaderPage.jsx`
- Delete: `frontend/src/components/tabs/AskTab.jsx`

- [ ] **Step 1: Rewrite ReaderPage.jsx**

Replace the entire contents of `frontend/src/pages/ReaderPage.jsx` with:

```jsx
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getWork } from "../api";
import AppShell from "../components/AppShell";
import AskAI from "../components/AskAI";
import SettingsOverlay from "../components/SettingsOverlay";
import Dashboard from "../components/dashboard/Dashboard";
import RawTextStack from "../components/stacks/RawTextStack";
import GraphStack from "../components/stacks/GraphStack";
import ArcsStack from "../components/stacks/ArcsStack";
import TimelineStack from "../components/stacks/TimelineStack";
import StoryStack from "../components/stacks/StoryStack";
import { useReaderPrefs } from "../hooks/useReaderPrefs";
import { Settings } from "lucide-react";

export default function ReaderPage() {
  const { id } = useParams();
  const [pkg, setPkg] = useState(null);
  const [error, setError] = useState(null);

  const [activeStack, setActiveStack] = useState(null); // null | raw | graph | arcs | timeline | story
  const [stackParams, setStackParams] = useState(null);

  const [askOpen, setAskOpen] = useState(false);
  const [askSeed, setAskSeed] = useState(null);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const prefs = useReaderPrefs();

  useEffect(() => {
    let cancelled = false;
    getWork(id)
      .then((r) => {
        if (!cancelled) setPkg(r);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  function openStack(target, params) {
    setStackParams(params || null);
    setActiveStack(target);
  }

  function closeStack() {
    setActiveStack(null);
  }

  function askAbout(question) {
    setAskSeed({ question, nonce: Date.now() });
  }

  function askAboutSelection(question) {
    setAskSeed({ question, autoSubmit: false, nonce: Date.now() });
  }

  function viewChapter(chapterId, paragraphIndex) {
    openStack("raw", { chapterId, paragraphIndex, nonce: Date.now() });
  }

  if (error) {
    return (
      <AppShell activeWorkId={id} right={null}>
        <div className="p-8 text-danger-600">{error}</div>
      </AppShell>
    );
  }

  if (!pkg) {
    return (
      <AppShell activeWorkId={id} right={null}>
        <div className="p-8 text-ink-600">加载中…</div>
      </AppShell>
    );
  }

  const ls = pkg.layered_summary || {};

  return (
    <>
      <AppShell activeWorkId={id} right={null}>
        <Dashboard id={id} pkg={pkg} ls={ls} onAsk={askAbout} onOpenStack={openStack} />
      </AppShell>

      {activeStack === "raw" && (
        <RawTextStack
          id={id}
          ls={ls}
          jump={stackParams}
          onBack={closeStack}
          onAskAboutSelection={askAboutSelection}
          prefs={prefs}
        />
      )}
      {activeStack === "graph" && <GraphStack id={id} onBack={closeStack} onViewChapter={viewChapter} />}
      {activeStack === "arcs" && <ArcsStack id={id} ls={ls} onBack={closeStack} />}
      {activeStack === "timeline" && <TimelineStack id={id} onBack={closeStack} onViewChapter={viewChapter} />}
      {activeStack === "story" && <StoryStack id={id} onBack={closeStack} />}

      <AskAI id={id} open={askOpen} onOpenChange={setAskOpen} seed={askSeed} />
      <SettingsOverlay open={settingsOpen} onClose={() => setSettingsOpen(false)} prefs={prefs} />
      <button
        type="button"
        onClick={() => setSettingsOpen(true)}
        aria-label="设置"
        className="fixed top-4 right-4 z-50 rounded-full border border-ink-300 bg-white p-2 shadow-sm2 hover:border-seal-600"
      >
        <Settings size={18} strokeWidth={1.5} className="text-ink-600" />
      </button>
    </>
  );
}
```

Notes on this rewrite:
- `askSeed` is set directly (not gated by `setAskOpen(true)` here) because `AskAI.jsx`'s own effect (Task 7, Step 1) already calls `onOpenChange(true)` whenever a new `seed.nonce` arrives — duplicating that here would be redundant.
- `viewChapter` now calls `openStack("raw", {...})` instead of the old `setTab("raw")`; the resulting `stackParams` is passed to `RawTextStack` as its `jump` prop, preserving the exact `{chapterId, paragraphIndex, nonce}` shape `RawTextTab` already expects.
- The old external `完整图谱 ↗` header link and the `<h1>{pkg.title}</h1>` header row are gone from this file — the title now lives in `HeroSection.jsx` (Task 11) and the external graph link now lives in `CharactersGraphPreviewSection.jsx` (Task 12), per Architecture Decision Log item 4.

- [ ] **Step 2: Delete the now-dead AskTab.jsx**

Run: `cd frontend && rtk grep -rn "AskTab" src/` to confirm there are zero remaining imports/references (the only prior reference was in the old `ReaderPage.jsx`, which this task just rewrote).
Expected: no output (no matches).

Then delete the file:
```bash
rm frontend/src/components/tabs/AskTab.jsx
```

- [ ] **Step 3: Run the automated test suite and build**

Run: `cd frontend && npm run test`
Expected: all previously-passing tests still pass (readingProgress, dashboardStats, useReaderPrefs, useAskFlow — 21 tests total across Tasks 2/3/4/6).

Run: `cd frontend && npm run build`
Expected: clean build, no errors, no unresolved imports.

- [ ] **Step 4: Manual browser verification**

Start both servers if not already running:
```bash
cd backend && uvicorn app.main:app --reload &
cd frontend && npm run dev &
```

Using the chrome-devtools MCP tools (or equivalent), navigate to `http://localhost:5173/works/715322215446` (real test work "白夜行") and verify, per design spec §10:

1. Dashboard loads showing all 7 sections in order: Hero (with meta-row + ghost-link) → 内容简介 → 你可能想问 → 人物关系 (character grid + mini graph preview + both graph links) → 情节脉络 (arc cards + "查看逐幕剧情正片→") → 时间轴 (4-event teaser) → 世界观设定.
2. Clicking each of the 5 `AnchorNav` pills smooth-scrolls to the matching section; scrolling manually updates the active pill (scroll-spy).
3. Clicking "查看完整图谱→" opens the full-screen `GraphStack`; the vis-network canvas renders; clicking a node/edge populates the right rail; "返回" closes it and the Dashboard's scroll position is unchanged from before opening.
4. Same open/back/scroll-preserved check for `ArcsStack` (chapter accordion + TOC rail) and `TimelineStack` (event list + detail rail).
5. Clicking "不看全景，直接读原文 →" (Hero) or the bottom "开始阅读原文 →" button opens `RawTextStack`: no right rail, immersive tag visible, reading-progress line visible (once some progress exists), font A-/A+ buttons and day/night toggle work and stay in sync with the global settings gear's controls (open the gear, change font size there, confirm the open RawTextStack toolbar reflects it live).
6. Clicking "查看逐幕剧情正片 →" opens `StoryStack`, single-column, beat accordion expands/generates text on click.
7. The floating "问AI" button opens the panel from both the Dashboard and from inside an open stack page; clicking a suggested question on the Dashboard opens/pre-fills+auto-submits the panel; submitting a new question appends to history.
8. The gear icon opens `SettingsOverlay` from both the Dashboard and from inside an open stack page; changing font size/theme there is reflected in `RawTextStack` when next opened.
9. In `TimelineStack`/`GraphStack`, click an event/edge with a "查看原文" link — confirm it opens `RawTextStack` and scrolls to the correct paragraph (the `onViewChapter`/`chapterId#pN` contract, Architecture Decision Log — verifies Task 15/16 didn't break the existing CharactersTab/GraphTab/TimelineTab `source_location` parsing, which was left untouched).

- [ ] **Step 5: Commit**

```bash
cd frontend && rtk git add -A
rtk git commit -m "feat: replace 9-tab ReaderPage with panorama-first Dashboard + stack navigation"
```

---

## Self-Review

**Spec coverage:**
- §1 (scope/constraints) → honored: no backend changes anywhere in this plan (confirmed via Architecture Decision Log #1); all 9 existing tab components reused, only `RawTextTab` gets a prop-signature change (Task 5) and `AskTab` is deleted-after-extraction (Task 16) — both explicitly required by the spec's own §2/§6, not scope creep.
- §2 (IA/nav, anchor-nav, global floating elements, CTA placement) → Tasks 9, 7, 8, 11, 14, 16.
- §3/§3.1 (7 Dashboard sections incl. StoryTab sub-link) → Tasks 11–14 (`ArcsPreviewSection`'s "查看逐幕剧情正片 →" button, Task 13 Step 1).
- §4 (5 stack sub-pages) → Task 15.
- §5 (right-rail split) → Task 15 Steps 2–4 (Graph/Arcs/Timeline keep rail via local `setRight`; Raw/Story render rail-free).
- §6 (cross-component contracts) → `onAsk`/`onAskAboutSelection` (Task 16 Step 1), `onViewChapter` chapterId#pN parsing (untouched inside CharactersTab/GraphTab/TimelineTab, exercised end-to-end in Task 16 Step 4.9), `useAccordionCache` (untouched inside StoryTab/ArcsTab), `setRight` (Task 15).
- §7 (data sources) → each Dashboard section/stack fetches exactly the endpoint the spec's table names (Tasks 11–14 use `pkg`/`ls` props already fetched by `ReaderPage`; `CharactersGraphPreviewSection`/`TimelinePreviewSection` call `getGraph`/`getTimeline` directly, matching the original tabs' own fetch calls).
- §8 (known limitations) → Architecture Decision Log items 1–4 explicitly document the three deferred/adapted items (word-count, graph-preview visualization, timeline-teaser selection criteria) with rationale instead of leaving them as ambiguous TODOs.
- §9 (relationship to prior bug fix) → no action needed; already committed as `9d32a7f`, confirmed unaffected since Task 5 doesn't touch the `chapterFetchRef` lazy-load logic.
- §10 (verification approach) → Task 16 Step 4 is a literal checklist matching this section, run against the real work `715322215446`.

**Placeholder scan:** searched this plan for "TBD", "TODO", "similar to Task", "add appropriate" — none found. Every step has complete, runnable code or an exact shell command with expected output.

**Type/signature consistency check:**
- `RawTextTab` props after Task 5: `{id, ls, jump, setRight, onAskAboutSelection, fontSize, theme, onStepFontSize, onToggleTheme}` — matches exactly how Task 15's `RawTextStack` calls it.
- `useReaderPrefs()` return shape `{fontSize, theme, stepFontSize, toggleTheme}` (Task 4) — matches `SettingsOverlay`'s destructuring (Task 8) and `RawTextStack`'s `prefs.fontSize`/`prefs.stepFontSize` usage (Task 15) and `ReaderPage`'s `prefs={prefs}` passthrough (Task 16).
- `useAskFlow(id)` return shape `{history, loaded, loading, error, runAsk}` (Task 6) — matches `AskAI.jsx`'s destructuring (Task 7).
- `openStack(target, params)` (Task 16) is called consistently as `onOpenStack("raw")` / `onOpenStack("graph")` etc. with no params from `Dashboard.jsx` (Task 14) and with a params object from `viewChapter` (Task 16) — `stackParams` defaults to `null` via `setStackParams(params || null)`, and `RawTextStack`'s `jump` prop tolerates `null` (existing `RawTextTab` behavior already handles `jump == null`, confirmed in the original file's cross-tab-jump effect which checks `if (jump && ...)`).
- `getReadingProgress`/`setReadingProgress`/`describeProgress` (Task 2) signatures are used identically in `RawTextTab.jsx` (Task 5), `HeroSection.jsx` (Task 11), and `RawTextStack.jsx` (Task 15) — all pass `(workId, ...)` with `workId` as the first arg, matching the module's exports.

No gaps or inconsistencies found.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-22-reader-dashboard-redesign.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints.

Which approach?
