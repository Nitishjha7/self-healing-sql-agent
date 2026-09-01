import { useEffect, useRef, useState } from "react";
import "./App.css";

// Empty by default: the Docker/nginx setup proxies /api on the same origin.
// A split deployment (frontend on Pages, backend on Cloud Run) sets
// VITE_API_BASE to the backend's URL at build time.
const API_BASE = import.meta.env.VITE_API_BASE || "";

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

// The conversation id is generated client-side and kept for the tab's lifetime.
// Server-generated ids would mean cookies or session state; this API is
// deliberately stateless apart from what the checkpointer stores under this key.
function newThreadId() {
  return `web-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export default function App() {
  const [turns, setTurns] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [threadId, setThreadId] = useState(newThreadId);
  const [memoryActive, setMemoryActive] = useState(null);
  const bottomRef = useRef(null);

  // A new thread id is all it takes to start over: the old conversation stays
  // checkpointed under its own key, this one simply has no history yet.
  function newConversation() {
    if (loading) return;
    setTurns([]);
    setInput("");
    setMemoryActive(null);
    setThreadId(newThreadId());
  }

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
      const res = await fetch(`${API_BASE}/api/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed, thread_id: threadId }),
      });

      if (res.status === 429) {
        // The demo shares one free LLM quota across all visitors, so being
        // throttled is a normal state to explain, not an error to dump.
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Too many questions — give it a minute.");
      }
      if (!res.ok) throw new Error(`Backend returned ${res.status}`);

      const data = await res.json();
      // The backend reports whether memory was actually active, not just
      // requested — the checkpointer can fail to set up and the agent then runs
      // stateless. Showing "memory on" in that case would be a lie the user
      // only discovers when a follow-up goes wrong.
      setMemoryActive(Boolean(data.memory_active));
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
            database error and rewrites the query — up to 3 times. Follow-up
            questions can refer back to earlier answers.
          </p>
        </div>
        <div className="header-actions">
          {memoryActive !== null && (
            <span
              className={`badge ${memoryActive ? "ok" : "warn"}`}
              title={
                memoryActive
                  ? "Conversation is checkpointed in Postgres — follow-ups can refer back."
                  : "The checkpointer is not available, so each question is answered on its own."
              }
            >
              {memoryActive ? "Memory on" : "Memory off"}
            </span>
          )}
          {turns.length > 0 && (
            <button className="toggle" onClick={newConversation} disabled={loading}>
              New conversation
            </button>
          )}
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
