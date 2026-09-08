import { useState } from "react";
import SqlBlock from "../components/SqlBlock.jsx";
import { BarChart, DonutChart } from "../components/Charts.jsx";
import { IconAlert, IconGrid, IconPause, IconSend } from "../components/Icons.jsx";

/**
 * Phase 5 — the dashboard built from "Create a dashboard for X".
 *
 * Every widget is a full agent run, which is why each one can show its own SQL
 * and retry count. Hiding that would have been easy, but then this would look
 * like any other BI tool — when the whole point is that behind every tile there
 * is a generated, self-healed query you can inspect.
 */

const SUGGESTIONS = [
  "Create a dashboard showing salary and headcount by department",
  "Show me a budget overview across locations",
  "Build a report of who earns the most in each department",
];

export default function GeneratedDashboard({ apiBase, threadId }) {
  const [request, setRequest] = useState("");
  const [dash, setDash] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function generate(text) {
    const trimmed = (text ?? request).trim();
    if (!trimmed || loading) return;

    setLoading(true);
    setError(null);
    setDash(null);

    try {
      const res = await fetch(`${apiBase}/api/dashboard`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request: trimmed, thread_id: threadId }),
      });

      if (res.status === 429) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Too many requests — give it a minute.");
      }
      if (!res.ok) throw new Error(`Backend returned ${res.status}`);

      setDash(await res.json());
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <div className="panel">
        <h3 className="panel-title">
          <IconGrid size={14} /> Build a dashboard from a sentence
        </h3>
        <p className="panel-sub">
          Your request is split into questions, each one runs through the same
          self-healing agent, and the widget for each is chosen from the shape of
          its result — not by another model call. Up to four widgets, because each
          one costs a full agent run.
        </p>

        <form
          className="composer-box"
          onSubmit={(e) => {
            e.preventDefault();
            generate();
          }}
        >
          <input
            className="input"
            value={request}
            onChange={(e) => setRequest(e.target.value)}
            placeholder="Create a dashboard showing…"
            disabled={loading}
          />
          <button className="send" type="submit" disabled={loading || !request.trim()}>
            <IconSend size={16} />
          </button>
        </form>

        {!dash && !loading && (
          <div className="chips" style={{ marginTop: 14 }}>
            {SUGGESTIONS.map((s) => (
              <button key={s} className="chip" onClick={() => generate(s)}>
                {s}
              </button>
            ))}
          </div>
        )}
      </div>

      {loading && (
        <div className="panel empty-panel">
          <p>Planning questions and running them…</p>
          <p className="muted-note">
            Each widget is a full agent run, so this takes longer than one question.
          </p>
        </div>
      )}

      {error && <div className="bubble agent error">{error}</div>}

      {dash?.error && <div className="bubble agent error">{dash.error}</div>}

      {dash && !dash.error && (
        <>
          <div className="dash-generated-head">
            <div>
              <h2 className="dash-title">{dash.title}</h2>
              <p className="muted-note">Created from your request · just now</p>
            </div>
            <PowerBiExport apiBase={apiBase} dashboard={dash} />
          </div>

          <div className="panels">
            {dash.widgets.map((w, i) => (
              <Widget key={i} widget={w} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/**
 * Phase 6 — take the generated dashboard into Power BI.
 *
 * Deliberately labelled an *export*, not an integration, in the UI as well as in
 * the code. Publishing to a Power BI workspace needs an Azure AD app and tenant
 * permissions this project does not have, and a button that implied otherwise
 * would be the same class of lie as a chart that flatters its data.
 */
function PowerBiExport({ apiBase, dashboard }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    if (data) {
      setOpen((o) => !o);
      return;
    }
    setBusy(true);
    try {
      const res = await fetch(`${apiBase}/api/dashboard/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(dashboard),
      });
      if (!res.ok) throw new Error(`Backend returned ${res.status}`);
      setData(await res.json());
      setOpen(true);
    } catch {
      // Export is an extra, not the product. A failure here should not take the
      // dashboard the user just generated down with it.
      setOpen(false);
    } finally {
      setBusy(false);
    }
  }

  function downloadPbids() {
    const url = URL.createObjectURL(
      new Blob([data.pbids], { type: "application/json" })
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `${data.title.replace(/[^\w -]/g, "")}.pbids`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="export-wrap">
      <button className="ghost-btn" onClick={load} disabled={busy}>
        {busy ? "Preparing…" : open ? "Hide Power BI export" : "Export to Power BI"}
      </button>

      {open && data && (
        <div className="panel export-panel">
          <h3 className="panel-title">Open this in Power BI Desktop</h3>
          <ol className="export-steps">
            {data.instructions.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ol>

          <button className="btn" onClick={downloadPbids}>
            Download .pbids
          </button>

          {data.queries.map((q) => (
            <div key={q.name} style={{ marginTop: 12 }}>
              <SqlBlock sql={q.script} title={`${q.name} — Power Query (M)`} />
            </div>
          ))}

          <p className="muted-note" style={{ marginTop: 12 }}>
            {data.note}
          </p>
        </div>
      )}
    </div>
  );
}

function Widget({ widget }) {
  const [showSql, setShowSql] = useState(false);

  return (
    <div className="panel">
      <div className="widget-head">
        <h3 className="panel-title">{widget.question}</h3>
        {widget.sql && (
          <button className="ghost-btn" onClick={() => setShowSql((s) => !s)}>
            {showSql ? "Hide SQL" : "View SQL"}
          </button>
        )}
      </div>

      {widget.retry_count > 0 && (
        <span className="chip warn" style={{ marginBottom: 10 }}>
          Self-healed after {widget.retry_count}{" "}
          {widget.retry_count === 1 ? "retry" : "retries"}
        </span>
      )}

      <WidgetBody widget={widget} />

      {showSql && widget.sql && <SqlBlock sql={widget.sql} title="Generated SQL" />}
    </div>
  );
}

function WidgetBody({ widget }) {
  // A question that needed a write, or came back empty, is reported rather than
  // dropped: a dashboard quietly missing a tile is worse than one that says which
  // question it could not answer.
  if (widget.type === "skipped") {
    return (
      <p className="widget-note">
        <IconPause size={14} /> {widget.note}
      </p>
    );
  }

  if (widget.type === "empty") {
    return (
      <p className="widget-note">
        <IconAlert size={14} /> {widget.note}
      </p>
    );
  }

  const rows = widget.rows || [];
  const columns = Object.keys(rows[0] || {});

  if (widget.type === "kpi") {
    const value = rows[0][columns[0]];
    return (
      <div className="kpi">
        <span className="kpi-value">{format(value)}</span>
        <span className="tile-label">{columns[0].replace(/_/g, " ")}</span>
      </div>
    );
  }

  if (widget.type === "donut") {
    return (
      <DonutChart
        data={rows.map((r) => ({ label: String(r[columns[0]]), value: r[columns[1]] }))}
      />
    );
  }

  if (widget.type === "bar") {
    return (
      <BarChart
        data={rows.map((r) => ({ label: String(r[columns[0]]), value: r[columns[1]] }))}
        valueFormat={format}
      />
    );
  }

  return (
    <div className="table-wrap">
      <table className="result">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 10).map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c}>{row[c] === null ? "—" : String(row[c])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 10 && (
        <p className="muted-note" style={{ padding: "8px 14px" }}>
          Showing 10 of {widget.row_count} rows
        </p>
      )}
    </div>
  );
}

/** Large numbers get thousands separators; everything else passes through. */
function format(v) {
  if (typeof v === "number") {
    return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, {
      maximumFractionDigits: 2,
    });
  }
  return String(v);
}

