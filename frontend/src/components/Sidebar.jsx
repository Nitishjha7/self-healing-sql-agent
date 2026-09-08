import {
  IconBrain,
  IconChart,
  IconChat,
  IconClock,
  IconDatabase,
  IconGrid,
  IconPlus,
  IconSettings,
  IconTable,
} from "./Icons.jsx";

/**
 * Left rail: brand, primary action, navigation, saved conversations, memory card.
 *
 * The conversation list is the only part that scrolls — see `.side-section` in
 * Shell.css. Scrolling the whole column used to slide the brand and the "New
 * Query" button off screen as soon as a few conversations existed.
 */

// Nav lives here rather than in App: App only needs to know which view is
// selected, not what the menu contains.
const NAV = [
  { id: "chat", label: "Chat", Icon: IconChat },
  { id: "dashboard", label: "Dashboard", Icon: IconGrid },
  { id: "build", label: "Build Dashboard", Icon: IconChart },
  { id: "schema", label: "Schema Explorer", Icon: IconTable },
  { id: "history", label: "Query History", Icon: IconClock },
  { id: "evals", label: "Evaluations", Icon: IconChart, badge: "20" },
  { id: "settings", label: "Settings", Icon: IconSettings },
];

export default function Sidebar({
  view,
  onView,
  onNew,
  busy,
  memoryActive,
  saved,
  activeThread,
  onOpen,
  onDelete,
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">
          <IconDatabase size={18} />
        </span>
        <div>
          <strong>PRISM INTEL</strong>
          <small>Self-Healing AI Data Agent</small>
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
          <p className="side-title">Conversations</p>
          <button className="icon-btn tiny" onClick={onNew} disabled={busy}>
            <IconPlus size={13} />
          </button>
        </div>

        {saved.length === 0 ? (
          <p className="side-empty">
            Nothing saved yet. Ask a question and this conversation appears here —
            and stays after a reload.
          </p>
        ) : (
          <ul className="side-list side-scroll">
            {saved.map((c) => (
              <li
                key={c.thread_id}
                title={c.title}
                className={c.thread_id === activeThread ? "on" : ""}
              >
                <button className="side-open" onClick={() => onOpen(c.thread_id)}>
                  <IconChat size={13} />
                  <span>{c.title}</span>
                  <em>{c.turns}</em>
                </button>
                <button
                  className="side-del"
                  title="Delete this conversation"
                  onClick={() => onDelete(c.thread_id)}
                >
                  ×
                </button>
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
