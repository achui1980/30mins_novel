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
