import { useEffect } from "react";

export default function SettingsTab({ cards, setRight }) {
  useEffect(() => {
    setRight(null);
  }, [setRight]);

  if (cards.length === 0) {
    return <div className="mx-auto max-w-3xl px-8 py-10 text-ink-600">暂无设定卡</div>;
  }
  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="grid grid-cols-2 gap-4">
        {cards.map((c, i) => (
          <div key={i} className="rounded-card border border-ink-300 bg-white p-4">
            <div className="font-medium text-ink-900">{c.title}</div>
            <div className="mt-2 text-sm text-ink-600">{c.content}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
