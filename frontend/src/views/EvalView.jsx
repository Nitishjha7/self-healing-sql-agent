import { EvalChart } from "../components/Charts.jsx";

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

export default function EvalView() {
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
