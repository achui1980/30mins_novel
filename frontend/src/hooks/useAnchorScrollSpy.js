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
