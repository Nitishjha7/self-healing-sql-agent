import {
  IconBrain,
  IconChart,
  IconChat,
  IconClock,
  IconDatabase,
  IconGrid,
  IconPanelLeft,
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
 *
 * **Collapsed mode** narrows it to an icon rail. This is not decoration: the
 * trace panel is 350px and the widest thing in the app is a result table, so on
 * a 1280px laptop the content column is the pane actually starved of room. What
 * survives the collapse is what the rail is *for* — moving between views, and
 * starting a new query. The conversation list and the memory card do not: both
 * are unreadable without their labels, and an icon that cannot be understood is
 * worse than one that is not there.
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
  collapsed,
  onToggle,
}) {
  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="brand">
        <span className="brand-mark">
          <IconDatabase size={18} />
        </span>
        {!collapsed && (
          <div className="brand-text">
            <strong>PRISM INTEL</strong>
            <small>Self-Healing AI Data Agent</small>
          </div>
        )}
        <button
          className="icon-btn tiny rail-toggle"
          onClick={onToggle}
          aria-expanded={!collapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <IconPanelLeft size={14} />
        </button>
      </div>

      {/* `title` on every collapsed control, because the label is the only thing
          that says what these do and collapsing takes it away. */}
      <button
        className="new-query"
        onClick={onNew}
        disabled={busy}
        title={collapsed ? "New Query" : undefined}
      >
        <IconPlus size={15} />
        <span>New Query</span>
      </button>

      <nav className="nav">
        {NAV.map(({ id, label, Icon, badge }) => (
          <button
            key={id}
            className={`nav-item ${view === id ? "active" : ""}`}
            onClick={() => onView(id)}
            title={collapsed ? label : undefined}
            aria-label={collapsed ? label : undefined}
          >
            <Icon size={15} />
            <span>{label}</span>
            {badge && <span className="nav-badge">{badge}</span>}
          </button>
        ))}
      </nav>

      {!collapsed && (
        <>
          <div className="side-section">
            <div className="side-head">
              <p className="side-title">Conversations</p>
              <button className="icon-btn tiny" onClick={onNew} disabled={busy}>
                <IconPlus size={13} />
              </button>
            </div>

            {saved.length === 0 ? (
              <p className="side-empty">
                Nothing saved yet. Ask a question and this conversation appears
                here — and stays after a reload.
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
        </>
      )}
    </aside>
  );
}
