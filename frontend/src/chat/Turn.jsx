import SqlBlock from "../components/SqlBlock.jsx";
import ResultTable from "./ResultTable.jsx";
import {
  IconCheck,
  IconClock,
  IconDatabase,
  IconRefresh,
  IconShield,
} from "../components/Icons.jsx";

/** One question and everything that came back for it. */

export default function Turn({ turn, pending, onDecide, busy }) {
  const retries = turn.retry_count ?? 0;

  return (
    <div className="turn">
      <div className="row user-row">
        <div className="bubble user">{turn.question}</div>
        <span className="avatar user-avatar">N</span>
      </div>

      {pending && (
        <div className="row">
          <span className="avatar bot">
            <IconDatabase size={15} />
          </span>
          <div className="bubble agent pending">
            <span className="dots">
              <i />
              <i />
              <i />
            </span>
            Generating SQL and running it…
          </div>
        </div>
      )}

      {turn.failed && (
        <div className="row">
          <span className="avatar bot">
            <IconDatabase size={15} />
          </span>
          <div className="bubble agent error">
            Couldn&apos;t reach the agent: {turn.failed}
          </div>
        </div>
      )}

      {/* The approval gate. The SQL is shown in full and unedited — asking
          someone to approve a statement they cannot read is not an approval,
          it is a rubber stamp with extra steps. */}
      {turn.awaiting_approval && !pending && (
        <div className="row">
          <span className="avatar bot warn">
            <IconShield size={15} />
          </span>
          <div className="bubble agent approval">
            <div className="approval-head">
              <span className="chip warn">Approval required</span>
              <span className="approval-note">
                This would modify data, so the agent paused before running it.
              </span>
            </div>

            <SqlBlock sql={turn.sql_query} title="Statement awaiting approval" />

            {onDecide ? (
              <div className="approval-actions">
                <button
                  className="btn danger"
                  disabled={busy}
                  onClick={() => onDecide(true)}
                >
                  Approve &amp; run
                </button>
                <button className="btn" disabled={busy} onClick={() => onDecide(false)}>
                  Reject
                </button>
              </div>
            ) : (
              <p className="approval-note">
                Superseded by a later question — this one was never run.
              </p>
            )}
          </div>
        </div>
      )}

      {turn.final_answer && (
        <div className="row">
          <span className="avatar bot">
            <IconDatabase size={15} />
          </span>
          <div className="answer-stack">
            <div className="bubble agent">
              <div className="answer">{turn.final_answer}</div>
              <div className="status-strip">
                {/* A restored turn carries the question, SQL and answer — the
                    trace and rows are per-turn state and were reset. Showing an
                    empty trace would imply the run had no steps, rather than
                    that they were not kept. */}
                {turn.restored ? (
                  <span className="muted-note">
                    <IconClock size={13} /> Restored from an earlier session
                  </span>
                ) : (
                  <span className="ok">
                    <IconCheck size={13} /> Query executed successfully
                  </span>
                )}
                {!turn.restored &&
                  (retries > 0 ? (
                    <span className="warn">
                      <IconRefresh size={13} /> Recovered after {retries}{" "}
                      {retries === 1 ? "retry" : "retries"}
                    </span>
                  ) : (
                    <span className="muted-note">
                      <IconRefresh size={13} /> No retries needed
                    </span>
                  ))}
                {turn.elapsed != null && (
                  <span className="muted-note">
                    <IconClock size={13} /> {turn.elapsed.toFixed(2)}s
                  </span>
                )}
                {turn.guardrail_flags?.length > 0 && (
                  <span className="warn" title={turn.guardrail_flags.join(", ")}>
                    <IconShield size={13} /> Output guard rewrote this
                  </span>
                )}
              </div>
            </div>

            {turn.sql_query && !turn.awaiting_approval && (
              <SqlBlock sql={turn.sql_query} />
            )}

            {turn.result_rows?.length > 0 && (
              <ResultTable rows={turn.result_rows} total={turn.row_count} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
