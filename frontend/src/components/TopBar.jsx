import { IconDatabase, IconMoon, IconPlus, IconSun } from "./Icons.jsx";

/** Page heading, connection pills, theme toggle. */

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}


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

export default function TopBar({ view, theme, onTheme, onNew, busy }) {
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
          <IconDatabase size={13} /> PostgreSQL 18
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
