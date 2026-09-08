import { useEffect, useState } from "react";
import { IconTable } from "../components/Icons.jsx";

/**
 * What the agent is actually told about the database.
 *
 * Row counts come from a live query; the column list and the description are
 * hand-written on the server. That is deliberate — this page exists to show the
 * *prompt*, and generating it from `information_schema` would make the page and
 * the prompt diverge.
 */
export default function SchemaView({ apiBase }) {
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
