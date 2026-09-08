import { useEffect, useRef, useState } from "react";
import "./Shell.css";

import Sidebar from "./components/Sidebar.jsx";
import TopBar from "./components/TopBar.jsx";
import FeatureStrip from "./components/FeatureStrip.jsx";

import ChatView from "./chat/ChatView.jsx";
import Composer from "./chat/Composer.jsx";
import TracePanel from "./chat/TracePanel.jsx";

import Dashboard from "./views/Dashboard.jsx";
import GeneratedDashboard from "./views/GeneratedDashboard.jsx";
import SchemaView from "./views/SchemaView.jsx";
import HistoryView from "./views/HistoryView.jsx";
import EvalView from "./views/EvalView.jsx";
import SettingsView from "./views/SettingsView.jsx";

/**
 * Application state and composition.
 *
 * Everything that renders lives in `components/`, `chat/` or `views/`. What stays
 * here is the state those pieces share — the conversation, which view is open,
 * the theme — and the calls that change it. This file used to be 819 lines and
 * held eight components; splitting it was about cohesion, not about tidiness:
 * `Turn` and `Sidebar` have nothing to say to each other, and keeping them in one
 * file meant every change to either risked the other.
 */

// Empty by default: both the docker-compose/nginx setup and the single-service
// deploy image serve this app on the same origin as the API. Only a split
// deployment needs VITE_API_BASE, set to the backend's URL at build time.
const API_BASE = import.meta.env.VITE_API_BASE || "";

// The conversation id is generated client-side and kept for the tab's lifetime.
// Server-generated ids would mean cookies or session state; this API is
// deliberately stateless apart from what the checkpointer stores under this key.
function newThreadId() {
  return `web-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * The thread id survives a reload.
 *
 * It used to be generated fresh on every page load, and that quietly broke the
 * feature it belonged to: conversations were still being checkpointed in
 * Postgres, but the UI could never find them again. Nothing was deleted —
 * everything was orphaned. Persisting the id is what makes the memory feature
 * visible instead of merely present.
 */
function loadThreadId() {
  try {
    return localStorage.getItem("threadId") || newThreadId();
  } catch {
    // Private windows and blocked site data throw. A fresh id still works for
    // this session; only the ability to return to it is lost.
    return newThreadId();
  }
}

export default function App() {
  const [turns, setTurns] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [threadId, setThreadId] = useState(loadThreadId);
  const [memoryActive, setMemoryActive] = useState(null);
  const [view, setView] = useState("chat");
  const [saved, setSaved] = useState([]);
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

  useEffect(() => {
    try {
      localStorage.setItem("threadId", threadId);
    } catch {
      // Same as the theme: the session still works, only the memory of it is lost.
    }
  }, [threadId]);

  // On first load, pull the saved conversations and restore whichever thread this
  // tab was last on. Without this the sidebar can list conversations the user is
  // unable to reopen, which is the same orphaning problem in a new costume.
  useEffect(() => {
    refreshSaved();
    restore(threadId, { silent: true });
    // Deliberately once, on mount: `threadId` changes are already handled by the
    // functions that change it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refreshSaved() {
    try {
      const res = await fetch(`${API_BASE}/api/conversations`);
      if (!res.ok) return;
      const data = await res.json();
      setSaved(data.conversations || []);
    } catch {
      // The sidebar list is a convenience. Losing it must not break the app.
    }
  }

  /** Rebuild a transcript from checkpointed history. */
  async function restore(id, { silent = false } = {}) {
    try {
      const res = await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(id)}`);
      if (!res.ok) {
        if (!silent) setTurns([]);
        return;
      }
      const data = await res.json();
      // Checkpointed history holds the question, the SQL and the answer — not
      // the trace or the rows, which are per-turn state and reset each turn.
      // Restored turns are marked so the UI can say so rather than imply the
      // trace simply had nothing in it.
      setTurns(
        (data.turns || []).map((t) => ({
          question: t.question,
          sql_query: t.sql_query,
          final_answer: t.answer,
          restored: true,
        }))
      );
      setThreadId(id);
      setMemoryActive(true);
      setView("chat");
    } catch {
      if (!silent) setTurns([]);
    }
  }

  // A new thread id is all it takes to start over: the old conversation stays
  // checkpointed under its own key, this one simply has no history yet.
  function newConversation() {
    if (loading) return;
    setTurns([]);
    setInput("");
    setMemoryActive(null);
    setThreadId(newThreadId());
    setView("chat");
    refreshSaved();
  }

  async function removeConversation(id) {
    try {
      await fetch(`${API_BASE}/api/conversations/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
    } catch {
      // Ignore: the refresh below shows whether it actually went.
    }
    if (id === threadId) newConversation();
    else refreshSaved();
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
      // The first answer in a thread is what makes it appear in the list, so the
      // sidebar has to refresh after a turn completes, not before.
      refreshSaved();
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
        saved={saved}
        activeThread={threadId}
        onOpen={restore}
        onDelete={removeConversation}
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

