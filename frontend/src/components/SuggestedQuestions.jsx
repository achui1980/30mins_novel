export default function SuggestedQuestions({ questions, onAsk }) {
  if (!questions || questions.length === 0) return null;
  return (
    <div>
      <h3 className="font-serif text-sm font-semibold text-ink-900">你可能想问</h3>
      <div className="mt-3 space-y-2">
        {questions.map((q, i) => (
          <button
            key={i}
            type="button"
            onClick={() => onAsk(q.question)}
            className="block w-full rounded-btn border border-ink-300 bg-white px-3 py-2 text-left text-sm text-ink-900 hover:border-seal-600 hover:bg-seal-100/30"
          >
            <div>{q.question}</div>
            {q.rationale && <div className="mt-1 text-xs text-ink-600">{q.rationale}</div>}
          </button>
        ))}
      </div>
    </div>
  );
}
