import { IconBrain, IconMoon, IconSun } from "../components/Icons.jsx";

/** Appearance, and what this session is currently doing. */
export default function SettingsView({ theme, onTheme, memoryActive, threadId }) {
  return (
    <div className="page">
      <div className="panel">
        <h3 className="panel-title">Appearance</h3>
        <div className="setting-row">
          <div>
            <strong>Theme</strong>
            <p className="muted-note">
              Dark is the default — this is a console for reading code and traces.
            </p>
          </div>
          <div className="seg">
            <button
              className={theme === "dark" ? "on" : ""}
              onClick={() => onTheme("dark")}
            >
              <IconMoon size={13} /> Dark
            </button>
            <button
              className={theme === "light" ? "on" : ""}
              onClick={() => onTheme("light")}
            >
              <IconSun size={13} /> Light
            </button>
          </div>
        </div>
      </div>

      <div className="panel">
        <h3 className="panel-title">This session</h3>
        <div className="setting-row">
          <div>
            <strong>Conversation memory</strong>
            <p className="muted-note">
              Reported by the backend, not assumed from the request — the
              checkpointer can fail to start and the agent then runs stateless.
            </p>
          </div>
          <span className={`chip ${memoryActive ? "ok" : "muted"}`}>
            <IconBrain size={13} />{" "}
            {memoryActive === null ? "Idle" : memoryActive ? "Active" : "Off"}
          </span>
        </div>
        <div className="setting-row">
          <div>
            <strong>Thread id</strong>
            <p className="muted-note">
              Generated in this tab. It is unauthenticated — anyone holding it can
              read or approve on this conversation, which is fine for a
              single-user demo and not for anything more.
            </p>
          </div>
          <code className="chip muted mono">{threadId}</code>
        </div>
      </div>
    </div>
  );
}
