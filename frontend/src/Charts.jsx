/**
 * Hand-rolled SVG chart primitives.
 *
 * No charting library: these are two forms over at most four categories, which
 * is a few dozen lines of SVG. Pulling in Recharts for that adds ~500KB to a
 * bundle whose whole job is one page, and hands over control of exactly the
 * details that matter here — mark geometry, label placement, theme tokens.
 *
 * Colours come from the validated categorical palette (slots 1-4) defined as CSS
 * custom properties in App.css, so light and dark are separate selected steps
 * rather than an automatic flip.
 */

const fmtMoney = (n) =>
  n >= 1000 ? `$${(n / 1000).toFixed(n >= 100000 ? 0 : 1)}k` : `$${n}`;

/**
 * Horizontal bars. Chosen over vertical because department names are words:
 * horizontal gives them a readable baseline instead of rotated tick labels.
 */
export function BarChart({ data, valueFormat = (v) => v, caption }) {
  const max = Math.max(...data.map((d) => d.value), 1);

  return (
    <div className="chart">
      <ul className="bars">
        {data.map((d, i) => (
          <li key={d.label} className="bar-row">
            <span className="bar-label">{d.label}</span>
            <span className="bar-track">
              <span
                className="bar-fill"
                style={{
                  width: `${(d.value / max) * 100}%`,
                  background: `var(--series-${(i % 4) + 1})`,
                }}
              />
            </span>
            {/* Value labels wear text tokens, never the series colour — the bar
                beside them already carries identity. */}
            <span className="bar-value">{valueFormat(d.value)}</span>
          </li>
        ))}
      </ul>
      {caption && <p className="chart-caption">{caption}</p>}
    </div>
  );
}

/**
 * Payroll against budget, per department. Both are currency, so they share one
 * axis — this is a grouped comparison, not a dual-axis chart.
 */
export function BudgetChart({ departments }) {
  const max = Math.max(...departments.map((d) => Math.max(d.budget, d.payroll)), 1);

  return (
    <div className="chart">
      <div className="legend">
        <span className="legend-item">
          <i style={{ background: "var(--series-1)" }} /> Salary spend
        </span>
        <span className="legend-item">
          <i style={{ background: "var(--series-4)" }} /> Budget
        </span>
      </div>

      <ul className="bars">
        {departments.map((d) => {
          const pct = Math.round((d.payroll / d.budget) * 100);
          return (
            <li key={d.name} className="bar-row grouped">
              <span className="bar-label">{d.name}</span>
              <span className="bar-track stacked">
                <span
                  className="bar-fill"
                  style={{
                    width: `${(d.payroll / max) * 100}%`,
                    background: "var(--series-1)",
                  }}
                />
                <span
                  className="bar-fill thin"
                  style={{
                    width: `${(d.budget / max) * 100}%`,
                    background: "var(--series-4)",
                  }}
                />
              </span>
              <span className="bar-value">{pct}%</span>
            </li>
          );
        })}
      </ul>
      <p className="chart-caption">
        Percentage is salary spend as a share of the department&apos;s budget.
      </p>
    </div>
  );
}

/**
 * The eval result. Three conditions, two bars each — this is the project's
 * signature number, so it gets a form that makes the comparison immediate.
 */
export function EvalChart({ runs }) {
  return (
    <div className="chart">
      <div className="legend">
        <span className="legend-item">
          <i style={{ background: "var(--series-2)" }} /> Retries off
        </span>
        <span className="legend-item">
          <i style={{ background: "var(--series-3)" }} /> Retries on
        </span>
      </div>

      <ul className="bars">
        {runs.map((r) => (
          <li key={r.condition} className="bar-row eval-row">
            <span className="bar-label">{r.condition}</span>
            <span className="eval-pair">
              <span className="bar-track">
                <span
                  className="bar-fill"
                  style={{
                    width: `${r.off}%`,
                    background: "var(--series-2)",
                  }}
                />
              </span>
              <span className="bar-track">
                <span
                  className="bar-fill"
                  style={{
                    width: `${r.on}%`,
                    background: "var(--series-3)",
                  }}
                />
              </span>
            </span>
            <span className={`bar-value ${r.on > r.off ? "gain" : ""}`}>
              {r.on > r.off ? `+${r.on - r.off}pp` : "no change"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export { fmtMoney };
