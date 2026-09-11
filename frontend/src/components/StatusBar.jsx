import { IconAlert, IconBrain, IconDatabase, IconRefresh, IconShield } from "./Icons.jsx";

/**
 * The status bar pinned along the bottom.
 *
 * This replaced a row of feature claims — "Self-healing", "Safe by design",
 * "Conversation memory", "Validation layer", "Observability". That strip was a
 * landing page pinned inside an application: it said the same five things
 * whether the agent was idle, mid-retry, or unable to reach Postgres, so it
 * carried no information at all. Worse, two of those claims could be false at
 * runtime — memory switches itself off when the checkpointer cannot start.
 *
 * A bar earns a permanent row of the viewport by changing. Everything on the
 * left is read from the running process (`/api/meta`), everything on the right
 * from the turn that just finished. If the backend is unreachable the bar says
 * so rather than continuing to advertise.
 */

function Field({ label, value, tone = "" }) {
  return (
    <span className={`sb-field ${tone}`}>
      <span className="sb-label">{label}</span>
      <span className="sb-value">{value}</span>
    </span>
  );
}

export default function StatusBar({ meta, turn, loading }) {
  // Three states, not two: "still loading" must not be drawn as "down", or the
  // bar flashes a false alarm on every page load.
  const state = meta === null ? "pending" : meta ? "ok" : "down";

  return (
    <footer className="status-bar">
      <div className="sb-group">
        <span className={`sb-state ${state}`}>
          <i className="dot" />
          {state === "ok" ? "Connected" : state === "pending" ? "Connecting" : "Backend unreachable"}
        </span>

        {meta && (
          <>
            <span className="sb-sep" />
            <span className="sb-field">
              <IconDatabase size={12} />
              <span className="sb-value">{meta.database}</span>
            </span>
            <span className="sb-sep" />
            <Field label="model" value={meta.model} />
            <span className="sb-sep" />
            {/* The direct/MCP toggle is invisible everywhere else in the UI, and
                it changes how every query reaches the database. */}
            <Field
              label="data access"
              value={meta.data_access === "mcp" ? "MCP tools" : "direct driver"}
            />
            <span className="sb-sep" />
            {/* Amber when an approved write would really commit. This is the one
                field on the bar where the safe value is the quiet one. */}
            <span className={`sb-field ${meta.writes === "commit" ? "warn" : ""}`}>
              {meta.writes === "commit" ? <IconAlert size={12} /> : <IconShield size={12} />}
              <span className="sb-value">approved writes {meta.writes}</span>
            </span>
            <span className="sb-sep" />
            <span className={`sb-field ${meta.memory ? "" : "muted"}`}>
              <IconBrain size={12} />
              <span className="sb-value">memory {meta.memory ? "on" : "off"}</span>
            </span>
            {/* Ordered last and marked optional: fields are laid out most- to
                least-informative, so whatever the bar has to give up first is
                the thing worth least. */}
            <span className="sb-sep optional" />
            <span className="sb-field optional">
              <IconRefresh size={12} />
              <span className="sb-value">retry budget {meta.max_retries}</span>
            </span>
          </>
        )}
      </div>

      <div className="sb-group right">
        <LastRun turn={turn} loading={loading} />
      </div>
    </footer>
  );
}

/** The right-hand half: what the most recent turn actually cost. */
function LastRun({ turn, loading }) {
  if (loading) return <span className="sb-run working">Running…</span>;
  if (!turn || turn.restored) return <span className="sb-run idle">No run yet</span>;
  if (turn.failed) return <span className="sb-run failed">Last run failed</span>;
  if (turn.awaiting_approval)
    return <span className="sb-run waiting">Waiting on your decision</span>;
  if (turn.final_answer === undefined) return <span className="sb-run idle">No run yet</span>;

  const retries = turn.retry_count || 0;
  const parts = [
    // The number the whole project is about, so it is named rather than
    // abbreviated to a bare digit.
    retries === 0 ? "first try" : `${retries} ${retries === 1 ? "retry" : "retries"}`,
  ];
  if (typeof turn.elapsed === "number") parts.push(`${turn.elapsed.toFixed(1)}s`);
  if (typeof turn.row_count === "number") {
    parts.push(`${turn.row_count} ${turn.row_count === 1 ? "row" : "rows"}`);
  }

  return (
    <span className={`sb-run ${retries > 0 ? "healed" : "clean"}`}>
      Last run · {parts.join(" · ")}
    </span>
  );
}
