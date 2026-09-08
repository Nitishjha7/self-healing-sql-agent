import SqlBlock from "../components/SqlBlock.jsx";
import { IconChat } from "../components/Icons.jsx";

/** Every question in this conversation, with the SQL it produced. */
export default function HistoryView({ turns, onAsk }) {
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
