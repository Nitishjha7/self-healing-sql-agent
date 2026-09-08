import Turn from "./Turn.jsx";

/** The transcript. Empty state offers starters; after an answer, follow-ups. */

const EXAMPLES = [
  "Which department has the highest average salary?",
  "Who works in Bangalore?",
  "Which departments have more than two employees?",
  "Delete all employees from HR",
];

// Follow-ups that only make sense with conversation memory — each one refers
// back instead of naming its subject. Shown after the first answer, because
// before that there is nothing to refer to.
const FOLLOW_UPS = [
  "How many people work there?",
  "What is that department's budget?",
  "Who is the highest paid among them?",
];

/* ------------------------------------------------------------------- chat */

export default function ChatView({ turns, loading, memoryActive, onAsk, onDecide, bottomRef }) {
  return (
    <main className="chat">
      {turns.length === 0 && !loading && (
        <div className="empty">
          <p className="empty-title">Try one of these</p>
          <div className="chips">
            {EXAMPLES.map((q) => (
              <button key={q} className="chip" onClick={() => onAsk(q)}>
                {q}
              </button>
            ))}
          </div>
          <p className="empty-hint">
            The last one is there on purpose: anything that would modify data
            stops and asks you to approve the exact statement first.
          </p>
        </div>
      )}

      {turns.map((turn, i) => (
        <Turn
          key={i}
          turn={turn}
          pending={loading && i === turns.length - 1}
          onDecide={i === turns.length - 1 ? onDecide : null}
          busy={loading}
        />
      ))}

      {/* Only offered once an answer exists to refer back to, and only when
          memory is actually on — suggesting "how many work there?" with the
          checkpointer down sets the user up to watch it fail. */}
      {memoryActive && !loading && turns.some((t) => t.final_answer) && (
        <div className="chips follow-ups">
          {FOLLOW_UPS.map((q) => (
            <button key={q} className="chip" onClick={() => onAsk(q)}>
              {q}
            </button>
          ))}
        </div>
      )}
      <div ref={bottomRef} />
    </main>
  );
}
