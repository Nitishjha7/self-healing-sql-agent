import { IconMoon, IconPlus, IconSun } from "./Icons.jsx";

/**
 * Page heading and the two actions that apply everywhere.
 *
 * This used to open with "Good morning, Nitish 👋" and carry a "Connected ·
 * PostgreSQL 18" pill pair. Both were dropped on purpose. The greeting named a
 * user the app has never identified — there is no auth here, so it was decoration
 * pretending to be personalisation — and the version pill was a string typed into
 * a component, which would have kept saying 18 against any other server. Both
 * facts now come from the backend and live in the status bar, where a fact that
 * can change belongs.
 */

const TITLES = {
  chat: [
    "Ask a question",
    // "In plain English" was dropped rather than shortened elsewhere: the title
    // above already says this is a question box, so the subtitle only has to
    // explain what happens after you ask. It also brings the line under the
    // width where it wrapped onto two.
    "The agent writes the SQL, runs it, and repairs it if Postgres rejects it.",
  ],
  dashboard: [
    "Overview",
    "Live figures from the database, and the measured evaluation result.",
  ],
  build: [
    "Build a Dashboard",
    "Describe what you want. Each question runs through the same self-healing agent.",
  ],
  schema: [
    "Schema Explorer",
    "Exactly what the agent is told about your database — nothing more.",
  ],
  history: ["Query History", "Every question in this conversation, with the SQL it produced."],
  evals: ["Evaluations", "Does the self-healing loop actually improve accuracy?"],
  settings: ["Settings", "Appearance, and what this session is currently doing."],
};

export default function TopBar({ view, theme, onTheme, onNew, busy }) {
  const [title, sub] = TITLES[view] || TITLES.chat;

  return (
    <header className="topbar">
      <div>
        <h1>{title}</h1>
        <p className="sub">{sub}</p>
      </div>

      <div className="topbar-actions">
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
