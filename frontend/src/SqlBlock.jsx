import { useState } from "react";
import { IconCode, IconCopy } from "./Icons.jsx";

/**
 * SQL shown with line numbers and highlighting.
 *
 * Highlighting is a small tokenizer rather than a syntax-highlighting library:
 * this renders exactly one dialect in one context, and the alternative ships a
 * grammar engine for every language to colour six keywords. It is also the
 * safer shape — the tokenizer emits React elements, so nothing here ever goes
 * near `dangerouslySetInnerHTML` with model-generated text.
 */

const KEYWORDS = new Set(
  `SELECT FROM WHERE JOIN INNER LEFT RIGHT FULL OUTER ON GROUP BY ORDER HAVING
   LIMIT OFFSET AS AND OR NOT IN IS NULL DISTINCT UNION ALL CASE WHEN THEN ELSE
   END ASC DESC INSERT INTO VALUES UPDATE SET DELETE WITH EXISTS BETWEEN LIKE`
    .split(/\s+/)
    .filter(Boolean)
);

const FUNCS = new Set(
  "COUNT SUM AVG MIN MAX ROUND COALESCE CAST LOWER UPPER ABS".split(" ")
);

/** Splits on quoted strings first, so a keyword inside a literal stays a literal. */
function tokenize(line) {
  const parts = [];
  const re = /('[^']*'|"[^"]*"|\b\d+(?:\.\d+)?\b|\w+|\s+|[^\w\s])/g;
  let m;
  while ((m = re.exec(line)) !== null) {
    const t = m[0];
    let cls = null;
    if (/^['"]/.test(t)) cls = "sql-str";
    else if (/^\d/.test(t)) cls = "sql-num";
    else if (KEYWORDS.has(t.toUpperCase())) cls = "sql-kw";
    else if (FUNCS.has(t.toUpperCase())) cls = "sql-fn";
    parts.push({ t, cls });
  }
  return parts;
}

export default function SqlBlock({ sql, title = "SQL Query" }) {
  const [copied, setCopied] = useState(false);
  const lines = sql.split("\n");

  function copy() {
    // Clipboard access can be refused (insecure origin, permissions). Failing
    // silently would leave the button claiming a success it never had.
    navigator.clipboard
      ?.writeText(sql)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => {});
  }

  return (
    <div className="card">
      <div className="card-head">
        <span className="card-title">
          <IconCode size={14} /> {title}
        </span>
        <button className="ghost-btn" onClick={copy}>
          <IconCopy size={13} /> {copied ? "Copied" : "Copy"}
        </button>
      </div>

      <div className="sql-body">
        {lines.map((line, i) => (
          <div className="sql-line" key={i}>
            <span className="sql-no">{i + 1}</span>
            <code>
              {tokenize(line).map((p, j) =>
                p.cls ? (
                  <span key={j} className={p.cls}>
                    {p.t}
                  </span>
                ) : (
                  <span key={j}>{p.t}</span>
                )
              )}
            </code>
          </div>
        ))}
      </div>
    </div>
  );
}
