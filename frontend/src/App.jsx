import { useEffect, useRef, useState } from "react";
import "./App.css";
import "./Shell.css";
import Dashboard from "./Dashboard.jsx";
import TracePanel from "./TracePanel.jsx";
import SqlBlock from "./SqlBlock.jsx";
import { SchemaView, HistoryView, EvalView, SettingsView } from "./Views.jsx";
import GeneratedDashboard from "./GeneratedDashboard.jsx";
import {
  IconActivity,
  IconBrain,
  IconChart,
  IconChat,
  IconCheck,
  IconClock,
  IconCopy,
  IconDatabase,
  IconGrid,
  IconMoon,
  IconPlus,
  IconRefresh,
  IconSend,
  IconSettings,
  IconShield,
  IconSun,
  IconTable,
} from "./Icons.jsx";

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

const NAV = [
  { id: "chat", label: "Chat", Icon: IconChat },
  { id: "dashboard", label: "Dashboard", Icon: IconGrid },
  { id: "build", label: "Build Dashboard", Icon: IconChart },
  { id: "schema", label: "Schema Explorer", Icon: IconTable },
  { id: "history", label: "Query History", Icon: IconClock },
  { id: "evals", label: "Evaluations", Icon: IconChart, badge: "20" },
  { id: "settings", label: "Settings", Icon: IconSettings },
];

const FEATURES = [
  { Icon: IconRefresh, title: "Self-healing", sub: "Up to 3 automatic retries" },
  { Icon: IconShield, title: "Safe by design", sub: "Writes need your approval" },
  { Icon: IconBrain, title: "Conversation memory", sub: "Context across questions" },
  { Icon: IconCheck, title: "Validation layer", sub: "Guards the final answer" },
  { Icon: IconActivity, title: "Observability", sub: "LangSmith tracing ready" },
];

// The conversation id is generated client-side and kept for the tab's lifetime.
// Server-generated ids would mean cookies or session state; this API is
// deliberately stateless apart from what the checkpointer stores under this key.
function newThreadId() {
  return `web-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

export default function App() {
  const [turns, setTurns] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [threadId, setThreadId] = useState(newThreadId);
  const [memoryActive, setMemoryActive] = useState(null);
  const [view, setView] = useState("chat");
  const [theme, setTheme] = useState(
    () => localStorage.getItem("theme") || "dark"
  );
  const bottomRef = useRef(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("theme", theme);
    } catch {
      // Private windows and blocked site data throw here. The theme still
      // applies for this session; only the memory of it is lost.
    }
  }, [theme]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, loading]);

  // A new thread id is all it takes to start over: the old conversation stays
  // checkpointed under its own key, this one simply has no history yet.
  function newConversation() {
    if (loading) return;
    setTurns([]);
    setInput("");
    setMemoryActive(null);
    setThreadId(newThreadId());
    setView("chat");
  }

  async function ask(question) {
    const trimmed = question.trim();
    if (!trimmed || loading) return;

    setInput("");
    setLoading(true);
    setView("chat");
    setTurns((prev) => [...prev, { question: trimmed, at: Date.now() }]);
    const started = performance.now();

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
      applyToLastTurn({ ...data, elapsed: (performance.now() - started) / 1000 });
    } catch (err) {
      applyToLastTurn({ failed: String(err.message || err) });
    } finally {
      setLoading(false);
    }
  }

  async function decide(approved) {
    if (loading) return;
    setLoading(true);
    const started = performance.now();

    try {
      const res = await fetch(`${API_BASE}/api/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadId, approved }),
      });

      if (res.status === 409) {
        // Already decided — a double click, or a stale tab. Not alarming, but
        // the pending card has to go: leaving it up implies a decision is still
        // outstanding when it is not.
        applyToLastTurn({
          awaiting_approval: false,
          final_answer:
            "This request was already decided elsewhere. Nothing further ran.",
        });
        return;
      }
      if (res.status === 429) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Too many requests — give it a minute.");
      }
      if (!res.ok) throw new Error(`Backend returned ${res.status}`);

      const data = await res.json();
      applyToLastTurn({ ...data, elapsed: (performance.now() - started) / 1000 });
    } catch (err) {
      applyToLastTurn({ failed: String(err.message || err) });
    } finally {
      setLoading(false);
    }
  }

  function applyToLastTurn(patch) {
    setTurns((prev) => {
      const next = [...prev];
      next[next.length - 1] = { ...next[next.length - 1], ...patch };
      return next;
    });
  }

  const lastTurn = turns[turns.length - 1] || null;
  const showTrace = view === "chat";

  return (
    <div className="shell">
      <Sidebar
        view={view}
        onView={setView}
        onNew={newConversation}
        busy={loading}
        memoryActive={memoryActive}
        turns={turns}
      />

      <div className="main">
        <TopBar
          view={view}
          theme={theme}
          onTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
          onNew={newConversation}
          busy={loading}
        />

        <div className={`workspace ${showTrace ? "" : "full"}`}>
          <div className="content-col">
            {view === "chat" && (
              <ChatView
                turns={turns}
                loading={loading}
                memoryActive={memoryActive}
                onAsk={ask}
                onDecide={decide}
                bottomRef={bottomRef}
              />
            )}
            {view === "dashboard" && <Dashboard apiBase={API_BASE} />}
            {view === "build" && (
              <GeneratedDashboard apiBase={API_BASE} threadId={threadId} />
            )}
            {view === "schema" && <SchemaView apiBase={API_BASE} />}
            {view === "history" && <HistoryView turns={turns} onAsk={ask} />}
            {view === "evals" && <EvalView />}
            {view === "settings" && (
              <SettingsView
                theme={theme}
                onTheme={setTheme}
                memoryActive={memoryActive}
                threadId={threadId}
              />
            )}

            {view === "chat" && (
              <Composer
                input={input}
                setInput={setInput}
                onSubmit={() => ask(input)}
                loading={loading}
              />
            )}
          </div>

          {showTrace && <TracePanel turn={lastTurn} pending={loading} />}
        </div>

        <FeatureStrip />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- sidebar */

function Sidebar({ view, onView, onNew, busy, memoryActive, turns }) {
  const questions = turns.map((t) => t.question);

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">
          <IconDatabase size={18} />
        </span>
        <div>
          <strong>SQL Copilot</strong>
          <small>Self-Healing Data Query Agent</small>
        </div>
      </div>

      <button className="new-query" onClick={onNew} disabled={busy}>
        <IconPlus size={15} /> New Query
      </button>

      <nav className="nav">
        {NAV.map(({ id, label, Icon, badge }) => (
          <button
            key={id}
            className={`nav-item ${view === id ? "active" : ""}`}
            onClick={() => onView(id)}
          >
            <Icon size={15} />
            <span>{label}</span>
            {badge && <span className="nav-badge">{badge}</span>}
          </button>
        ))}
      </nav>

      <div className="side-section">
        <div className="side-head">
          <p className="side-title">Conversation</p>
          <button className="icon-btn tiny" onClick={onNew} disabled={busy}>
            <IconPlus size={13} />
          </button>
        </div>

        {questions.length === 0 ? (
          <p className="side-empty">
            Nothing yet — your questions appear here as you ask them.
          </p>
        ) : (
          <ul className="side-list">
            {questions.map((q, i) => (
              <li key={i} title={q} className={i === questions.length - 1 ? "on" : ""}>
                <IconChat size={13} />
                <span>{q}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="side-card">
        <div className="side-card-head">
          <strong>Conversation Memory</strong>
          <span className={`chip ${memoryActive ? "ok" : "muted"}`}>
            {memoryActive === null ? "Idle" : memoryActive ? "Active" : "Off"}
          </span>
        </div>
        <div className="side-card-body">
          <p>
            Follow-up questions refer back to earlier answers, checkpointed in
            Postgres so they survive a restart.
          </p>
          <IconBrain size={22} />
        </div>
      </div>
    </aside>
  );
}

/* ----------------------------------------------------------------- topbar */

const TITLES = {
  chat: null,
  dashboard: ["Overview", "Live figures from the database, and the measured evaluation result."],
  build: [
    "Build a Dashboard",
    "Describe what you want. Each question runs through the same self-healing agent.",
  ],
  schema: ["Schema Explorer", "Exactly what the agent is told about your database — nothing more."],
  history: ["Query History", "Every question in this conversation, with the SQL it produced."],
  evals: ["Evaluations", "Does the self-healing loop actually improve accuracy?"],
  settings: ["Settings", "Appearance, and what this session is currently doing."],
};

function TopBar({ view, theme, onTheme, onNew, busy }) {
  const t = TITLES[view];

  return (
    <header className="topbar">
      <div>
        {t ? (
          <>
            <h1>{t[0]}</h1>
            <p className="sub">{t[1]}</p>
          </>
        ) : (
          <>
            <h1>
              {greeting()}, Nitish <span className="wave">👋</span>
            </h1>
            <p className="sub">Ask anything about your database in natural language.</p>
          </>
        )}
      </div>

      <div className="topbar-actions">
        <span className="pill ok">
          <i className="dot" /> Connected
        </span>
        <span className="pill">
          <IconDatabase size={13} /> PostgreSQL 16
        </span>
        <button
          className="icon-btn"
          onClick={onTheme}
          title={theme === "dark" ? "Switch to light" : "Switch to dark"}
        >
          {theme === "dark" ? <IconSun size={15} /> : <IconMoon size={15} />}
        </button>
        <button className="new-query compact" onClick={onNew} disabled={busy}>
          <IconPlus size={14} /> New Query
        </button>
      </div>
    </header>
  );
}

/* ------------------------------------------------------------------- chat */

function ChatView({ turns, loading, memoryActive, onAsk, onDecide, bottomRef }) {
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

function Turn({ turn, pending, onDecide, busy }) {
  const retries = turn.retry_count ?? 0;

  return (
    <div className="turn">
      <div className="row user-row">
        <div className="bubble user">{turn.question}</div>
        <span className="avatar user-avatar">N</span>
      </div>

      {pending && (
        <div className="row">
          <span className="avatar bot">
            <IconDatabase size={15} />
          </span>
          <div className="bubble agent pending">
            <span className="dots">
              <i />
              <i />
              <i />
            </span>
            Generating SQL and running it…
          </div>
        </div>
      )}

      {turn.failed && (
        <div className="row">
          <span className="avatar bot">
            <IconDatabase size={15} />
          </span>
          <div className="bubble agent error">
            Couldn&apos;t reach the agent: {turn.failed}
          </div>
        </div>
      )}

      {/* The approval gate. The SQL is shown in full and unedited — asking
          someone to approve a statement they cannot read is not an approval,
          it is a rubber stamp with extra steps. */}
      {turn.awaiting_approval && !pending && (
        <div className="row">
          <span className="avatar bot warn">
            <IconShield size={15} />
          </span>
          <div className="bubble agent approval">
            <div className="approval-head">
              <span className="chip warn">Approval required</span>
              <span className="approval-note">
                This would modify data, so the agent paused before running it.
              </span>
            </div>

            <SqlBlock sql={turn.sql_query} title="Statement awaiting approval" />

            {onDecide ? (
              <div className="approval-actions">
                <button
                  className="btn danger"
                  disabled={busy}
                  onClick={() => onDecide(true)}
                >
                  Approve &amp; run
                </button>
                <button className="btn" disabled={busy} onClick={() => onDecide(false)}>
                  Reject
                </button>
              </div>
            ) : (
              <p className="approval-note">
                Superseded by a later question — this one was never run.
              </p>
            )}
          </div>
        </div>
      )}

      {turn.final_answer && (
        <div className="row">
          <span className="avatar bot">
            <IconDatabase size={15} />
          </span>
          <div className="answer-stack">
            <div className="bubble agent">
              <div className="answer">{turn.final_answer}</div>
              <div className="status-strip">
                <span className="ok">
                  <IconCheck size={13} /> Query executed successfully
                </span>
                {retries > 0 ? (
                  <span className="warn">
                    <IconRefresh size={13} /> Recovered after {retries}{" "}
                    {retries === 1 ? "retry" : "retries"}
                  </span>
                ) : (
                  <span className="muted-note">
                    <IconRefresh size={13} /> No retries needed
                  </span>
                )}
                {turn.elapsed != null && (
                  <span className="muted-note">
                    <IconClock size={13} /> {turn.elapsed.toFixed(2)}s
                  </span>
                )}
                {turn.guardrail_flags?.length > 0 && (
                  <span className="warn" title={turn.guardrail_flags.join(", ")}>
                    <IconShield size={13} /> Output guard rewrote this
                  </span>
                )}
              </div>
            </div>

            {turn.sql_query && !turn.awaiting_approval && (
              <SqlBlock sql={turn.sql_query} />
            )}

            {turn.result_rows?.length > 0 && (
              <ResultTable rows={turn.result_rows} total={turn.row_count} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ResultTable({ rows, total }) {
  const columns = Object.keys(rows[0]);
  const capped = total > rows.length;

  function download() {
    // A CSV built in the browser from data already on screen: no round trip,
    // and nothing here the user cannot already see.
    const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = [
      columns.join(","),
      ...rows.map((r) => columns.map((c) => esc(r[c])).join(",")),
    ].join("\n");

    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "query-result.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="card">
      <div className="card-head">
        <span className="card-title">
          <IconTable size={14} /> Query Result ({total} {total === 1 ? "row" : "rows"}
          {capped && `, showing ${rows.length}`})
        </span>
        <button className="ghost-btn" onClick={download}>
          <IconCopy size={13} /> CSV
        </button>
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

/* --------------------------------------------------------------- composer */

function Composer({ input, setInput, onSubmit, loading }) {
  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <div className="composer-box">
        <input
          className="input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a follow-up question…"
          disabled={loading}
          autoFocus
        />
        <button className="send" type="submit" disabled={loading || !input.trim()}>
          <IconSend size={16} />
        </button>
      </div>
      <p className="composer-hint">Press Enter to send</p>
    </form>
  );
}

/* ---------------------------------------------------------------- footer */

function FeatureStrip() {
  return (
    <footer className="feature-strip">
      {FEATURES.map(({ Icon, title, sub }) => (
        <div className="feature" key={title}>
          <span className="feature-icon">
            <Icon size={14} />
          </span>
          <div>
            <strong>{title}</strong>
            <small>{sub}</small>
          </div>
        </div>
      ))}
    </footer>
  );
}
