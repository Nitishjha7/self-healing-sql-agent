import { IconCopy, IconTable } from "../components/Icons.jsx";

/** Query rows, with a client-side CSV export of what is already on screen. */

export default function ResultTable({ rows, total }) {
  const columns = Object.keys(rows[0]);
  const capped = total > rows.length;

  function download() {
    // A CSV built in the browser from data already on screen: no round trip,
    // and nothing here the user cannot already see.
    const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = [
      columns.join(","),
      ...rows.map((r) => columns.map((c) => esc(r[c])).join(",")),
    ].join("\n");

    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "query-result.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="card">
      <div className="card-head">
        <span className="card-title">
          <IconTable size={14} /> Query Result ({total} {total === 1 ? "row" : "rows"}
          {capped && `, showing ${rows.length}`})
        </span>
        <button className="ghost-btn" onClick={download}>
          <IconCopy size={13} /> CSV
        </button>
      </div>
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
            {rows.map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c}>{row[c] === null ? "—" : String(row[c])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- composer */
