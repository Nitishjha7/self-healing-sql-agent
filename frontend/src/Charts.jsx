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

/**
 * Headcount split as a donut.
 *
 * A donut is defensible here and rarely elsewhere: four categories, parts of a
 * known whole, and the question is "roughly what share" rather than "which is
 * bigger by how much" — the comparison a bar answers better. Every slice is
 * direct-labelled in the legend with both its count and its percentage, so the
 * reading never depends on judging arc lengths, and identity never rests on
 * colour alone.
 */
export function DonutChart({ data }) {
  const total = data.reduce((s, d) => s + d.value, 0) || 1;
  const R = 62;
  const STROKE = 26;
  const C = 2 * Math.PI * R;

  let offset = 0;

  return (
    <div className="chart donut-wrap">
      <svg width="150" height="150" viewBox="0 0 150 150" role="img">
        <title>Employees by department</title>
        {data.map((d, i) => {
          const frac = d.value / total;
          const dash = frac * C;
          // 2px surface-coloured gap between segments, so adjacent fills read as
          // separate marks rather than one continuous ring.
          const el = (
            <circle
              key={d.label}
              cx="75"
              cy="75"
              r={R}
              fill="none"
              stroke={`var(--series-${(i % 4) + 1})`}
              strokeWidth={STROKE}
              strokeDasharray={`${Math.max(dash - 2, 0)} ${C - Math.max(dash - 2, 0)}`}
              strokeDashoffset={-offset}
              transform="rotate(-90 75 75)"
            />
          );
          offset += dash;
          return el;
        })}
        <text
          x="75"
          y="71"
          textAnchor="middle"
          fill="var(--text)"
          fontSize="21"
          fontWeight="650"
        >
          {total}
        </text>
        <text x="75" y="88" textAnchor="middle" fill="var(--muted)" fontSize="10.5">
          employees
        </text>
      </svg>

      <ul className="donut-legend">
        {data.map((d, i) => (
          <li key={d.label}>
            <i style={{ background: `var(--series-${(i % 4) + 1})` }} />
            <span>
              {d.label} ({d.value})
            </span>
            <span className="pct">{Math.round((d.value / total) * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export { fmtMoney };
