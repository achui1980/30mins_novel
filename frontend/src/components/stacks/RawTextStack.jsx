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
