import { useEffect, useRef, useState } from "react";
import "./App.css";
import "./Shell.css";
import Dashboard from "./Dashboard.jsx";
import TracePanel from "./TracePanel.jsx";

// Empty by default: both the docker-compose/nginx setup and the single-service
// deploy image serve this app on the same origin as the API. Only a split
// deployment needs VITE_API_BASE, set to the backend's URL at build time.
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
  const [view, setView] = useState("chat");
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

  async function decide(approved) {
    if (loading) return;
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/api/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadId, approved }),
      });

      if (res.status === 409) {
        // Already decided — a double click, or a stale tab. Not an error worth
        // alarming the user about, but the pending card has to go: leaving it up
        // implies a decision is still outstanding when it is not.
        setTurns((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          next[next.length - 1] = {
            ...last,
            awaiting_approval: false,
            final_answer:
              last.final_answer ||
              "This request was already decided elsewhere. Nothing further ran.",
          };
          return next;
        });
        return;
      }
      if (res.status === 429) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Too many requests — give it a minute.");
      }
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


  const lastTurn = turns[turns.length - 1] || null;

  return (
    <div className="shell">
      <Sidebar
        view={view}
        onView={setView}
        onNew={newConversation}
        busy={loading}
        memoryActive={memoryActive}
        questions={turns.map((t) => t.question)}
      />

      <div className="main">
        <header className="topbar">
          <div>
            <h1>
              {view === "chat" ? "Ask your database" : "Overview"}
            </h1>
            <p className="sub">
              {view === "chat"
                ? "Plain English in, SQL out. If the query fails, the agent reads the database error and rewrites it."
                : "Live figures from the database, and the measured result for the self-healing loop."}
            </p>
          </div>
          <div className="header-actions">
            {memoryActive !== null && (
              <span
                className={`pill ${memoryActive ? "ok" : "warn"}`}
                title={
                  memoryActive
                    ? "Conversation is checkpointed in Postgres — follow-ups can refer back."
                    : "The checkpointer is not available, so each question is answered on its own."
                }
              >
                <i className="dot" /> Memory {memoryActive ? "on" : "off"}
              </span>
            )}
            <span className="pill muted">PostgreSQL 16</span>
          </div>
        </header>

        {view === "dashboard" ? (
          <Dashboard apiBase={API_BASE} />
        ) : (
          <div className="workspace">
            <div className="chat-col">
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
                      The last one is there on purpose: anything that would modify
                      data stops and asks you to approve the exact statement first.
                    </p>
                  </div>
                )}

                {turns.map((turn, i) => (
                  <Turn
                    key={i}
                    turn={turn}
                    pending={loading && i === turns.length - 1}
                    onDecide={i === turns.length - 1 ? decide : null}
                    busy={loading}
                  />
                ))}

                {/* Only offered once an answer exists to refer back to, and only
                    when memory is actually on — suggesting "how many work there?"
                    with the checkpointer down sets the user up to watch it fail. */}
                {memoryActive && !loading && turns.some((t) => t.final_answer) && (
                  <div className="chips follow-ups">
                    {FOLLOW_UPS.map((q) => (
                      <button key={q} className="chip" onClick={() => ask(q)}>
                        {q}
                      </button>
                    ))}
                  </div>
                )}
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
                  placeholder="Ask about employees, departments, salaries…"
                  disabled={loading}
                  autoFocus
                />
                <button
                  className="send"
                  type="submit"
                  disabled={loading || !input.trim()}
                >
                  {loading ? "Thinking…" : "Ask"}
                </button>
              </form>
            </div>

            <TracePanel turn={lastTurn} pending={loading} />
          </div>
        )}
      </div>
    </div>
  );
}

function Sidebar({ view, onView, onNew, busy, memoryActive, questions }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">⌘</span>
        <div>
          <strong>SQL Copilot</strong>
          <small>Self-healing data query agent</small>
        </div>
      </div>

      <button className="new-query" onClick={onNew} disabled={busy}>
        + New conversation
      </button>

      <nav className="nav">
        <button
          className={`nav-item ${view === "chat" ? "active" : ""}`}
          onClick={() => onView("chat")}
        >
          Chat
        </button>
        <button
          className={`nav-item ${view === "dashboard" ? "active" : ""}`}
          onClick={() => onView("dashboard")}
        >
          Dashboard
        </button>
      </nav>

      {questions.length > 0 && (
        <div className="side-section">
          <p className="side-title">This conversation</p>
          <ul className="side-list">
            {questions.map((q, i) => (
              <li key={i} title={q}>
                {q}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="side-card">
        <div className="side-card-head">
          <strong>Conversation memory</strong>
          <span className={`pill small ${memoryActive ? "ok" : "muted"}`}>
            {memoryActive === null ? "idle" : memoryActive ? "active" : "off"}
          </span>
        </div>
        <p>
          Checkpointed in Postgres, so follow-up questions can refer back to
          earlier answers — and survive a restart.
        </p>
      </div>
    </aside>
  );
}
function Turn({ turn, pending, onDecide, busy }) {
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

      {/* The approval gate. The SQL is shown in full and unedited — asking
          someone to approve a statement they cannot read is not an approval,
          it is a rubber stamp with extra steps. */}
      {turn.awaiting_approval && !pending && (
        <div className="bubble agent approval">
          <div className="approval-head">
            <span className="badge stop">Approval required</span>
            <span className="approval-note">
              This would modify data, so the agent paused before running it.
            </span>
          </div>

          <pre className="sql">{turn.sql_query}</pre>

          {onDecide ? (
            <div className="approval-actions">
              <button
                className="btn danger"
                disabled={busy}
                onClick={() => onDecide(true)}
              >
                Approve &amp; run
              </button>
              <button
                className="btn"
                disabled={busy}
                onClick={() => onDecide(false)}
              >
                Reject
              </button>
            </div>
          ) : (
            <p className="approval-note">
              Superseded by a later question — this one was never run.
            </p>
          )}
        </div>
      )}

      {turn.final_answer && (
        <>
          <div className="bubble agent">
            <div className="answer">{turn.final_answer}</div>
            <div className="meta">
              <Badge retries={retries} />
              {turn.guardrail_flags?.length > 0 && (
                <span className="badge warn" title={turn.guardrail_flags.join(", ")}>
                  Output guard rewrote this
                </span>
              )}
            </div>
          </div>

          {turn.sql_query && (
            <div className="card">
              <div className="card-head">
                <span className="card-title">SQL</span>
                <CopyButton text={turn.sql_query} />
              </div>
              <pre className="sql">{turn.sql_query}</pre>
            </div>
          )}

          {turn.result_rows?.length > 0 && (
            <ResultTable rows={turn.result_rows} total={turn.row_count} />
          )}

          {/* The full trace lives in the side panel; this stays as a fallback
              for narrow screens, where that panel is not on screen at all. */}
          <button
            className="toggle inline-toggle"
            onClick={() => setOpen((o) => !o)}
          >
            {open ? "Hide" : "Show"} execution trace
          </button>
          {open && (
            <ol className="logs boxed">
              {(turn.logs || []).map((line, i) => (
                <li key={i} className={logClass(line)}>
                  {line}
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </div>
  );
}

function ResultTable({ rows, total }) {
  const columns = Object.keys(rows[0]);
  const capped = total > rows.length;

  return (
    <div className="card">
      <div className="card-head">
        <span className="card-title">
          Result · {total} {total === 1 ? "row" : "rows"}
          {capped && <span className="muted-note"> (showing first {rows.length})</span>}
        </span>
      </div>
      <div className="table-wrap">
        <table className="result">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c}>{row[c] === null ? "—" : String(row[c])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CopyButton({ text }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="toggle"
      onClick={() => {
        // Clipboard access can be denied (insecure origin, permissions). Failing
        // silently would leave the button claiming success it did not have.
        navigator.clipboard
          ?.writeText(text)
          .then(() => {
            setDone(true);
            setTimeout(() => setDone(false), 1500);
          })
          .catch(() => {});
      }}
    >
      {done ? "Copied" : "Copy"}
    </button>
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
