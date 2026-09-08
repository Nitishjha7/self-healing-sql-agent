import {
  IconActivity,
  IconAlert,
  IconCheck,
  IconClock,
  IconPause,
  IconRefresh,
  IconShield,
} from "../components/Icons.jsx";

/**
 * The agent's execution trace, rendered as a timeline.
 *
 * This panel is the product, not decoration. The whole claim of the project is
 * that the agent reads a database error and repairs its own query — and a chat
 * bubble showing only the final answer is exactly the view in which that claim
 * is invisible. The retry exists on screen only if the failure does too.
 */

const KINDS = {
  error: { Icon: IconAlert, cls: "err", sub: "Query rejected by the database" },
  retry: { Icon: IconRefresh, cls: "warn", sub: "Using the error to fix the query" },
  gate: { Icon: IconPause, cls: "warn", sub: "Human decision on a write" },
  guard: { Icon: IconShield, cls: "warn", sub: "Rewrote the answer before sending" },
  ok: { Icon: IconCheck, cls: "ok", sub: null },
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

/** Short label under a step, so the timeline reads without expanding anything. */
function subtitle(kind, head) {
  if (KINDS[kind].sub) return KINDS[kind].sub;
  const h = head.toLowerCase();
  if (h.startsWith("generating")) return "Creating the initial SQL";
  if (h.startsWith("generated sql")) return "Statement ready";
  if (h.startsWith("execution succeeded")) return "Ran against PostgreSQL";
  if (h.startsWith("synthesized")) return "Turning rows into an answer";
  if (h.startsWith("write ")) return "Approved write";
  if (h.startsWith("giving up")) return "Retry budget exhausted";
  return null;
}

export default function TracePanel({ turn, pending }) {
  const logs = turn?.logs || [];
  const retries = turn?.retry_count ?? 0;

  return (
    <aside className="trace">
      <div className="trace-head">
        <IconActivity size={16} />
        <h2>Self-Healing Agent Trace</h2>
        {retries > 0 && (
          <span className="chip warn">
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
          <span className="step-icon">
            <IconRefresh size={13} className="spin" />
          </span>
          <div className="step-body">
            <span className="step-head">Working…</span>
            <span className="step-sub">Generating and executing SQL</span>
          </div>
        </div>
      )}

      <ol className="steps">
        {logs.map((line, i) => {
          const kind = classify(line);
          const { Icon, cls } = KINDS[kind];
          const { head, detail } = split(line);
          const sub = subtitle(kind, head);

          return (
            <li key={i} className={`step ${cls}`}>
              <span className={`step-icon ${cls}`}>
                <Icon size={13} />
              </span>
              <div className="step-body">
                <span className="step-head">{head}</span>
                {sub && <span className="step-sub">{sub}</span>}
                {detail && kind === "error" && (
                  <pre className="step-detail">
                    <span className="step-detail-label">Error</span>
                    {detail}
                  </pre>
                )}
                {detail && kind !== "error" && (
                  <span className="step-sub">{detail}</span>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {turn?.final_answer && (
        <dl className="trace-summary">
          <div>
            <dt>
              <IconRefresh size={13} /> Retries
            </dt>
            <dd>{retries} / 3</dd>
          </div>
          {turn.elapsed != null && (
            <div>
              <dt>
                <IconClock size={13} /> Total time
              </dt>
              <dd>{turn.elapsed.toFixed(2)}s</dd>
            </div>
          )}
          <div>
            <dt>
              <IconShield size={13} /> Output guard
            </dt>
            {/* "clean" and "never ran" have to look different, or a guard that
                silently does nothing is indistinguishable from one that works. */}
            <dd className={turn.guardrail_flags?.length ? "flagged" : ""}>
              {turn.guardrail_flags?.length
                ? turn.guardrail_flags.join(", ")
                : "clean"}
            </dd>
          </div>
          <div>
            <dt>
              <IconCheck size={13} /> Status
            </dt>
            <dd>
              <span className="chip ok">Success</span>
            </dd>
          </div>
        </dl>
      )}
    </aside>
  );
}
