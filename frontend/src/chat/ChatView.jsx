import Turn from "./Turn.jsx";

/** The transcript. Empty state offers starters; after an answer, follow-ups. */

// Bangalore now holds two departments (Engineering + Data Science, ~64 people
// combined) and every department has 9+ employees, so the two questions this
// used to ask — "who works there" and "which departments have more than two
// people" — either dump a 64-name list into a one-or-two-sentence prompt or
// return a trivially-true answer for all eight. Replaced with a JOIN over the
// third table (a query shape chip #1 doesn't already cover) and a narrower
// version of the Bangalore question that collapses to one clean answer instead
// of a wall of names.
const EXAMPLES = [
  "Which department has the highest average salary?",
  "Which department has the most people in Bangalore?",
  "How many active projects does each department have?",
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
