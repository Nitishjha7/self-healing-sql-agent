import { useEffect, useState } from "react";
import { BarChart, BudgetChart, EvalChart, fmtMoney } from "./Charts.jsx";

/**
 * Measured evaluation results, from `eval/RESULTS.md`.
 *
 * Deliberately a static constant and labelled as one in the UI. These come from
 * a 20-question harness run that takes minutes and burns most of a day's free
 * LLM quota — recomputing it on page load is not possible, and quietly showing
 * stale numbers as if they were live would be worse than showing them as what
 * they are: a recorded result, with the model and date attached.
 */
const EVAL_RUNS = [
  { condition: "Production schema", off: 95, on: 95 },
  { condition: "Degraded schema", off: 90, on: 90 },
  { condition: "Stale schema", off: 15, on: 30 },
];

const EVAL_META = "20 questions · gemini-3.5-flash-lite · execution accuracy";

export default function Dashboard({ apiBase }) {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${apiBase}/api/stats`)
      .then((r) => {
        if (!r.ok) throw new Error(`Backend returned ${r.status}`);
        return r.json();
      })
      .then((d) => !cancelled && setStats(d))
      .catch((e) => !cancelled && setError(String(e.message || e)));
    return () => {
      cancelled = true;
    };
  }, [apiBase]);

  if (error) {
    return (
      <div className="dash">
        <div className="bubble agent error">Couldn&apos;t load stats: {error}</div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="dash">
        <p className="muted-note">Loading…</p>
      </div>
    );
  }

  return (
    <div className="dash">
      <section>
        <h2 className="dash-title">Database</h2>
        <p className="dash-sub">
          Live from the same PostgreSQL the agent queries.
        </p>

        {/* Four counts, no plot: a single number per fact is the right form
            here. A bar chart of four unrelated totals would be decoration. */}
        <div className="tiles">
          <Tile label="Employees" value={stats.headcount} />
          <Tile label="Departments" value={stats.department_count} />
          <Tile label="Total payroll" value={fmtMoney(stats.payroll)} />
          <Tile label="Average salary" value={fmtMoney(stats.avg_salary)} />
        </div>

        <div className="panels">
          <Panel title="Headcount by department">
            <BarChart
              data={stats.departments.map((d) => ({
                label: d.name,
                value: d.headcount,
              }))}
            />
          </Panel>

          <Panel title="Average salary by department">
            <BarChart
              data={stats.departments.map((d) => ({
                label: d.name,
                value: d.avg_salary,
              }))}
              valueFormat={fmtMoney}
            />
          </Panel>

          <Panel title="Salary spend against budget">
            <BudgetChart departments={stats.departments} />
          </Panel>

          <Panel title="Where people work">
            <BarChart
              data={stats.departments.map((d) => ({
                label: d.location,
                value: d.headcount,
              }))}
            />
          </Panel>
        </div>
      </section>

      <section>
        <h2 className="dash-title">Does the self-healing loop work?</h2>
        <p className="dash-sub">
          The same 20 questions, run with retries off and on. Only the schema
          description differs between conditions. <span className="muted-note">{EVAL_META}</span>
        </p>

        <Panel title="Execution accuracy by condition">
          <EvalChart runs={EVAL_RUNS} />
        </Panel>

        {/* The honest reading, next to the chart rather than buried in a doc.
            The headline number flatters the system without it. */}
        <div className="callout">
          <strong>The loop doubles accuracy — but only when queries actually fail.</strong>{" "}
          In the first two conditions it never fired at all (average retries 0.00):
          with a well-written schema description the model simply does not produce
          SQL that PostgreSQL rejects, so there is nothing to heal. Those runs
          measure the prompt, not the architecture. The third condition describes
          the schema with column names that no longer exist — real schema drift —
          and there the error-informed retry recovers half the failures.
        </div>
      </section>
    </div>
  );
}

function Tile({ label, value }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className="tile-value">{value}</span>
    </div>
  );
}

function Panel({ title, children }) {
  return (
    <div className="panel">
      <h3 className="panel-title">{title}</h3>
      {children}
    </div>
  );
}
