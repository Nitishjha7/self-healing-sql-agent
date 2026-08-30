import { useEffect, useRef, useState } from "react";
import "./App.css";

const EXAMPLES = [
  "Which department has the highest average salary?",
  "Who works in Bangalore?",
  "Which departments have more than two employees?",
  "Delete all employees from HR",
];

export default function App() {
  const [turns, setTurns] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, loading]);

  async function ask(question) {
    const trimmed = question.trim();
    if (!trimmed || loading) return;

    setInput("");
    setLoading(true);
    setTurns((prev) => [...prev, { question: trimmed }]);

    try {
      const res = await fetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });
      if (!res.ok) throw new Error(`Backend returned ${res.status}`);
      const data = await res.json();
      setTurns((prev) => {
        const next = [...prev];
        next[next.length - 1] = { ...next[next.length - 1], ...data };
        return next;
      });
    } catch (err) {
      setTurns((prev) => {
        const next = [...prev];
        next[next.length - 1] = {
          ...next[next.length - 1],
          failed: String(err.message || err),
        };
        return next;
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>Self-Healing SQL Agent</h1>
          <p className="sub">
            Ask in plain English. If the generated SQL fails, the agent reads the
            database error and rewrites the query — up to 3 times.
          </p>
        </div>
      </header>

      <main className="chat">
        {turns.length === 0 && !loading && (
          <div className="empty">
            <p className="empty-title">Try one of these</p>
            <div className="chips">
              {EXAMPLES.map((q) => (
                <button key={q} className="chip" onClick={() => ask(q)}>
                  {q}
                </button>
              ))}
            </div>
            <p className="empty-hint">
              The last one is blocked on purpose — the agent only ever runs
              read-only queries.
            </p>
          </div>
        )}

        {turns.map((turn, i) => (
          <Turn key={i} turn={turn} pending={loading && i === turns.length - 1} />
        ))}
        <div ref={bottomRef} />
      </main>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
      >
        <input
          className="input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about employees, departments, salaries..."
          disabled={loading}
          autoFocus
        />
        <button className="send" type="submit" disabled={loading || !input.trim()}>
          {loading ? "Thinking..." : "Ask"}
        </button>
      </form>
    </div>
  );
}

function Turn({ turn, pending }) {
  const [open, setOpen] = useState(false);
  const retries = turn.retry_count ?? 0;

  return (
    <div className="turn">
      <div className="bubble user">{turn.question}</div>

      {pending && (
        <div className="bubble agent pending">
          <span className="dots">
            <i />
            <i />
            <i />
          </span>
          Generating SQL and running it…
        </div>
      )}

      {turn.failed && (
        <div className="bubble agent error">
          Couldn&apos;t reach the agent: {turn.failed}
        </div>
      )}

      {turn.final_answer && (
        <div className="bubble agent">
          <div className="answer">{turn.final_answer}</div>

          <div className="meta">
            <Badge retries={retries} />
            <button className="toggle" onClick={() => setOpen((o) => !o)}>
              {open ? "Hide" : "Show"} SQL &amp; steps
            </button>
          </div>

          {open && (
            <div className="details">
              {turn.sql_query && (
                <>
                  <div className="details-label">Executed SQL</div>
                  <pre className="sql">{turn.sql_query}</pre>
                </>
              )}
              <div className="details-label">Execution trace</div>
              <ol className="logs">
                {(turn.logs || []).map((line, i) => (
                  <li key={i} className={logClass(line)}>
                    {line}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Badge({ retries }) {
  if (retries === 0) {
    return <span className="badge ok">First try</span>;
  }
  return (
    <span className="badge warn">
      Self-healed after {retries} {retries === 1 ? "retry" : "retries"}
    </span>
  );
}

// The trace is the point of this UI, so failures and repairs are colour-coded
// rather than rendered as an undifferentiated wall of log lines.
function logClass(line) {
  const l = line.toLowerCase();
  if (l.startsWith("execution failed") || l.startsWith("blocked")) return "log-err";
  if (l.startsWith("retry")) return "log-warn";
  if (l.startsWith("execution succeeded")) return "log-ok";
  return "";
}
