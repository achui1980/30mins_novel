import { useState } from "react";

/**
 * Shared state management for "accordion + fetch-on-open + cache" UI patterns
 * used by StoryTab (beats) and ArcsTab (chapter summaries).
 *
 * Single-open-at-a-time accordion: `open` holds the currently expanded index
 * (or null). `itemState` is a dict keyed by index holding `{ loading, error, data }`
 * for whatever was fetched for that item.
 *
 * `toggle(index, fetchFn, shouldSkipFetch)`:
 * - Closes the accordion if `index` is already open.
 * - Otherwise opens it and, unless `shouldSkipFetch(existing)` returns true
 *   (defaults to "already cached or in flight"), calls `fetchFn()` and stores
 *   the resolved value under `itemState[index].data` (or the error message
 *   under `itemState[index].error`).
 *
 * `toggle` is a plain function (not tied to a single call site), so the same
 * reference can be wired up to multiple UI elements (e.g. a chapter list item
 * and a matching entry in a side-panel navigation list) and both will drive
 * the exact same open/cache state — this is relied on by ArcsTab.
 */
export function useAccordionCache() {
  const [open, setOpen] = useState(null);
  const [itemState, setItemState] = useState({});

  async function toggle(index, fetchFn, shouldSkipFetch) {
    if (open === index) {
      setOpen(null);
      return;
    }
    setOpen(index);
    const existing = itemState[index];
    const skip = shouldSkipFetch
      ? shouldSkipFetch(existing)
      : !!existing && !!(existing.loading || existing.data);
    if (skip) return;
    setItemState((s) => ({ ...s, [index]: { loading: true } }));
    try {
      const data = await fetchFn();
      setItemState((s) => ({ ...s, [index]: { loading: false, data } }));
    } catch (e) {
      setItemState((s) => ({ ...s, [index]: { loading: false, error: e.message } }));
    }
  }

  return { open, itemState, toggle };
}
