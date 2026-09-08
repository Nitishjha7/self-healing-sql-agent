import { useEffect, useState } from "react";
import { BarChart, BudgetChart, DonutChart, EvalChart, fmtMoney } from "./Charts.jsx";
import { EVAL_RUNS } from "./Views.jsx";
import { IconBuilding, IconMoney, IconTrend, IconUsers } from "./Icons.jsx";

const EVAL_META = "20 questions · gemini-3.5-flash-lite · execution accuracy";

export default function Dashboard({ apiBase }) {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let dead = false;
    fetch(`${apiBase}/api/stats`)
      .then((r) => {
        if (!r.ok) throw new Error(`Backend returned ${r.status}`);
        return r.json();
      })
      .then((d) => !dead && setStats(d))
      .catch((e) => !dead && setError(String(e.message || e)));
    return () => {
      dead = true;
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

  const top = [...stats.departments].sort((a, b) => b.avg_salary - a.avg_salary)[0];

  return (
    <div className="dash">
      <section>
        {/* Four counts, no plot: one number per fact is the right form here.
            A chart of four unrelated totals would be decoration. */}
        <div className="tiles">
          <Tile
            label="Total Employees"
            value={stats.headcount}
            Icon={IconUsers}
            tone="var(--series-1)"
          />
          <Tile
            label="Average Salary"
            value={fmtMoney(stats.avg_salary)}
            Icon={IconMoney}
            tone="var(--series-3)"
          />
          <Tile
            label="Departments"
            value={stats.department_count}
            Icon={IconBuilding}
            tone="var(--series-2)"
          />
          <Tile
            label="Highest Paid"
            value={fmtMoney(stats.max_salary)}
            sub={`in ${top.name}`}
            Icon={IconTrend}
            tone="var(--series-4)"
          />
        </div>
      </section>

      <section>
        <h2 className="dash-title">Workforce</h2>
        <p className="dash-sub">
          Live from the same PostgreSQL the agent queries — no cached copy.
        </p>

        <div className="panels">
          <div className="panel">
            <h3 className="panel-title">Average salary by department</h3>
            <BarChart
              data={stats.departments.map((d) => ({
                label: d.name,
                value: d.avg_salary,
              }))}
              valueFormat={fmtMoney}
            />
          </div>

          <div className="panel">
            <h3 className="panel-title">Employees by department</h3>
            <DonutChart
              data={stats.departments.map((d) => ({
                label: d.name,
                value: d.headcount,
              }))}
            />
          </div>

          <div className="panel">
            <h3 className="panel-title">Salary spend against budget</h3>
            <BudgetChart departments={stats.departments} />
          </div>

          <div className="panel">
            <h3 className="panel-title">Where people work</h3>
            <BarChart
              data={stats.departments.map((d) => ({
                label: d.location,
                value: d.headcount,
              }))}
            />
          </div>
        </div>
      </section>

      <section>
        <h2 className="dash-title">Does the self-healing loop work?</h2>
        <p className="dash-sub">
          The same 20 questions, run with retries off and on. Only the schema
          description differs between conditions.{" "}
          <span className="muted-note">{EVAL_META}</span>
        </p>

        <div className="panel">
          <h3 className="panel-title">Execution accuracy by condition</h3>
          <EvalChart runs={EVAL_RUNS} />
        </div>

        {/* The honest reading sits next to the chart rather than buried in a
            doc. The headline number flatters the system without it. */}
        <div className="callout" style={{ marginTop: 14 }}>
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

function Tile({ label, value, sub, Icon, tone }) {
  return (
    <div className="tile tile-with-icon">
      <span
        className="tile-icon"
        style={{ background: `color-mix(in srgb, ${tone} 18%, transparent)`, color: tone }}
      >
        <Icon size={18} />
      </span>
      {/* Stacked explicitly: these are spans, so without a column flex context
          the label and the value flow onto one line and spill out of the tile. */}
      <div className="tile-text">
        <span className="tile-label">{label}</span>
        <span className="tile-value">{value}</span>
        {sub && <span className="tile-sub">{sub}</span>}
      </div>
    </div>
  );
}
