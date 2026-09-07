/**
 * The agent's execution trace, rendered as a timeline.
 *
 * This panel is the product, not decoration. The whole claim of the project is
 * that the agent reads a database error and repairs its own query — and a chat
 * bubble showing the final answer is exactly the view in which that claim is
 * invisible. The retry only exists on screen if the failure does too.
 */

const KINDS = {
  error: { icon: "!", cls: "err" },
  retry: { icon: "↻", cls: "warn" },
  ok: { icon: "✓", cls: "ok" },
  gate: { icon: "⏸", cls: "warn" },
  guard: { icon: "⚑", cls: "warn" },
};

/** The backend sends prose log lines; this is the one place that reads them. */
function classify(line) {
  const l = line.toLowerCase();
  if (l.startsWith("execution failed") || l.startsWith("blocked")) return "error";
  if (l.startsWith("retry")) return "retry";
  if (l.startsWith("human ") || l.startsWith("resumed without")) return "gate";
  if (l.startsWith("output guard")) return "guard";
  return "ok";
}

/** "Retry 1: regenerating SQL after error: <long postgres message>" */
function split(line) {
  const at = line.indexOf(": ");
  if (at > 0 && at < 60) {
    return { head: line.slice(0, at), detail: line.slice(at + 2) };
  }
  return { head: line, detail: null };
}

export default function TracePanel({ turn, pending }) {
  const logs = turn?.logs || [];
  const retries = turn?.retry_count ?? 0;

  return (
    <aside className="trace">
      <div className="trace-head">
        <h2>Agent trace</h2>
        {retries > 0 && (
          <span className="badge warn">
            {retries} {retries === 1 ? "retry" : "retries"}
          </span>
        )}
      </div>

      {logs.length === 0 && !pending && (
        <p className="muted-note trace-empty">
          Ask a question and every step the agent takes shows up here — the SQL it
          wrote, what the database said back, and any repair it made.
        </p>
      )}

      {pending && (
        <div className="step running">
          <span className="step-icon spin">◌</span>
          <div className="step-body">
            <span className="step-head">Working…</span>
          </div>
        </div>
      )}

      <ol className="steps">
        {logs.map((line, i) => {
          const kind = classify(line);
          const { icon, cls } = KINDS[kind];
          const { head, detail } = split(line);
          return (
            <li key={i} className={`step ${cls}`}>
              <span className={`step-icon ${cls}`}>{icon}</span>
              <div className="step-body">
                <span className="step-head">{head}</span>
                {detail && (
                  <pre className={`step-detail ${kind === "error" ? "err" : ""}`}>
                    {detail}
                  </pre>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {turn?.final_answer && (
        <dl className="trace-summary">
          <div>
            <dt>Retries</dt>
            <dd>
              {retries} / 3
            </dd>
          </div>
          <div>
            <dt>Steps</dt>
            <dd>{logs.length}</dd>
          </div>
          <div>
            <dt>Memory</dt>
            <dd>{turn.memory_active ? "on" : "off"}</dd>
          </div>
          <div>
            <dt>Output guard</dt>
            {/* "clean" and "never ran" have to look different, or a guard that
                silently does nothing is indistinguishable from one that works. */}
            <dd className={turn.guardrail_flags?.length ? "flagged" : ""}>
              {turn.guardrail_flags?.length
                ? turn.guardrail_flags.join(", ")
                : "clean"}
            </dd>
          </div>
        </dl>
      )}
    </aside>
  );
}
