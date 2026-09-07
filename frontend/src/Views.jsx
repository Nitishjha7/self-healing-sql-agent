import { useEffect, useState } from "react";
import SqlBlock from "./SqlBlock.jsx";
import { EvalChart } from "./Charts.jsx";
import { IconBrain, IconChat, IconMoon, IconSun, IconTable } from "./Icons.jsx";

/**
 * The remaining nav destinations.
 *
 * Each one shows something the system actually has. A nav item that opens an
 * empty "coming soon" panel is worse than no nav item — it tells the person
 * looking at the app that the parts they cannot see may be equally hollow.
 */

/* --------------------------------------------------------- schema explorer */

export function SchemaView({ apiBase }) {
  const [schema, setSchema] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let dead = false;
    fetch(`${apiBase}/api/schema`)
      .then((r) => {
        if (!r.ok) throw new Error(`Backend returned ${r.status}`);
        return r.json();
      })
      .then((d) => !dead && setSchema(d))
      .catch((e) => !dead && setError(String(e.message || e)));
    return () => {
      dead = true;
    };
  }, [apiBase]);

  if (error) return <div className="page"><div className="bubble agent error">{error}</div></div>;
  if (!schema) return <div className="page"><p className="muted-note">Loading…</p></div>;

  return (
    <div className="page">
      <div className="panels two">
        {schema.tables.map((t) => (
          <div className="panel" key={t.name}>
            <h3 className="panel-title">
              <IconTable size={14} /> {t.name}
              <span className="chip muted">{t.rows} rows</span>
            </h3>
            <table className="result schema-table">
              <thead>
                <tr>
                  <th>Column</th>
                  <th>Type</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {t.columns.map((c) => (
                  <tr key={c.name}>
                    <td className="mono">{c.name}</td>
                    <td className="muted-note">{c.type}</td>
                    <td className="muted-note">{c.note || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>

      <div className="panel">
        <h3 className="panel-title">What the model actually receives</h3>
        <p className="panel-sub">
          Not the DDL — a hand-written description. It carries example values and
          states outright that <code>employees</code> has no department-name
          column, so a join is mandatory. Introspection would give the columns but
          not that guidance, and this keeps the prompt cost fixed.
        </p>
        <pre className="plain-block">{schema.description}</pre>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------- query history */

export function HistoryView({ turns, onAsk }) {
  const answered = turns.filter((t) => t.sql_query);

  if (answered.length === 0) {
    return (
      <div className="page">
        <div className="panel empty-panel">
          <IconChat size={22} />
          <p>No questions yet in this conversation.</p>
          <p className="muted-note">
            History is per-conversation and lives in this tab. Starting a new
            conversation gives you a fresh thread; the old one stays checkpointed
            under its own id.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="page history">
      {answered.map((t, i) => (
        <div className="panel" key={i}>
          <div className="history-head">
            <div>
              <strong>{t.question}</strong>
              <p className="muted-note">
                {t.retry_count > 0
                  ? `Self-healed after ${t.retry_count} ${
                      t.retry_count === 1 ? "retry" : "retries"
                    }`
                  : "First try"}
                {t.elapsed != null && ` · ${t.elapsed.toFixed(2)}s`}
                {t.row_count != null && ` · ${t.row_count} rows`}
              </p>
            </div>
            <button className="ghost-btn" onClick={() => onAsk(t.question)}>
              Run again
            </button>
          </div>
          <SqlBlock sql={t.sql_query} />
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------ evaluations */

/**
 * Measured results, from `eval/RESULTS.md`.
 *
 * Deliberately a static constant, and labelled as one on screen. The harness
 * takes minutes and burns most of a day's free LLM quota, so recomputing it on
 * page load is not possible — and showing a stale number as if it were live
 * would be worse than showing it as what it is: a recorded result with the
 * model and question count attached.
 */
export const EVAL_RUNS = [
  { condition: "Production schema", off: 95, on: 95, retries: "0.00" },
  { condition: "Degraded schema", off: 90, on: 90, retries: "0.00" },
  { condition: "Stale schema", off: 15, on: 30, retries: "2.25" },
];

export function EvalView() {
  return (
    <div className="page">
      <div className="tiles">
        <MiniTile label="Questions" value="20" />
        <MiniTile label="Conditions" value="3" />
        <MiniTile label="Best delta" value="+15pp" tone="ok" />
        <MiniTile label="Model" value="flash-lite" small />
      </div>

      <div className="panel">
        <h3 className="panel-title">Execution accuracy by condition</h3>
        <p className="panel-sub">
          The same 20 questions, run with retries off and on. Only the schema
          description differs between conditions.
        </p>
        <EvalChart runs={EVAL_RUNS} />
      </div>

      <div className="panel">
        <h3 className="panel-title">How correctness is decided</h3>
        <p className="panel-sub">
          Both the gold query and the agent&apos;s query are executed and their
          result sets compared — the standard execution-accuracy metric. Not SQL
          string matching, because many different queries are equally correct;
          and not an LLM judge, because that moves the reliability problem into a
          component nobody is measuring.
        </p>
      </div>

      {/* The honest reading sits next to the number, not buried in a doc. The
          headline flatters the system without it. */}
      <div className="callout">
        <strong>The loop doubles accuracy — but only when queries actually fail.</strong>{" "}
        In the first two conditions it never fired at all (average retries 0.00):
        with a well-written schema description the model simply does not produce
        SQL that PostgreSQL rejects, so there is nothing to heal. Those runs
        measure the prompt, not the architecture. The third describes the schema
        with column names that no longer exist — real schema drift — and there
        the error-informed retry recovers half the failures.
      </div>
    </div>
  );
}

function MiniTile({ label, value, tone, small }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className={`tile-value ${tone || ""} ${small ? "small" : ""}`}>{value}</span>
    </div>
  );
}

/* --------------------------------------------------------------- settings */

export function SettingsView({ theme, onTheme, memoryActive, threadId }) {
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
