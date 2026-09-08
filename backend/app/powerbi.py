"""Phase 6 — taking a generated dashboard into Power BI.

**This is not "Power BI integration", and calling it that would be wrong.**
Pushing a dataset into the Power BI service needs an Azure AD app registration, a
tenant, and workspace permissions — none of which this project has, and none of
which a portfolio demo should have.

What **can** be built, and genuinely works, is an export: two artifacts that Power
BI Desktop opens directly.

1. **`.pbids`** — Power BI\u2019s own data-source descriptor. Double-click it and
   Desktop prompts to connect to Postgres. Credentials **never** go into this
   file; Power BI asks for them itself and keeps them in its credential store.
2. **A Power Query (M) script** per widget — carrying exactly the SQL the agent
   generated. Paste it into the Advanced Editor and that query becomes a table.

So the dashboard the agent built becomes a **live query** in Power BI rather than
a frozen CSV — the user can add filters, relationships and their own visuals on
top of it.
"""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse


def _connection() -> tuple[str, str]:
    """Pull host:port and the database name out of `DATABASE_URL`.

    The username and password are deliberately left out. This file is downloaded
    by the user and lives on their disk — putting credentials in it would be the
    same mistake as putting an API key in `.env.example`.
    """
    dsn = os.environ.get("DATABASE_URL", "postgresql://agent:agent@localhost:5432/employees")
    parsed = urlparse(dsn)
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    database = (parsed.path or "/employees").lstrip("/")
    return f"{host}:{port}", database


def build_pbids() -> str:
    """Power BI Data Source file (JSON)."""
    server, database = _connection()
    return json.dumps(
        {
            "version": "0.1",
            "connections": [
                {
                    "details": {
                        "protocol": "postgresql",
                        "address": {"server": server, "database": database},
                    },
                    # DirectQuery so the dashboard stays live. Import mode would
                    # take a snapshot, and the Power BI dashboard would then drift
                    # silently out of date with this database.
                    "mode": "DirectQuery",
                }
            ],
        },
        indent=2,
    )


def _safe_name(question: str, index: int) -> str:
    """Turn a question into a Power Query identifier.

    M allows spaces in query names but then they must be quoted everywhere, and
    duplicate names silently overwrite one another — which is why the index prefix
    is always applied.
    """
    words = re.sub(r"[^A-Za-z0-9 ]", "", question).split()[:5]
    stem = "".join(w.capitalize() for w in words) or "Query"
    return f"Q{index}_{stem}"


def build_m_script(question: str, sql: str, index: int) -> dict:
    """Power Query M for one widget.

    The SQL must be escaped before it goes into an M string literal: in M a `"` is
    written as `""`. Without that, a query filtering on a plain string literal
    would still work, but any double-quoted identifier would break the script.
    """
    server, database = _connection()
    escaped = sql.replace('"', '""')

    script = (
        "let\n"
        f'    Source = PostgreSQL.Database("{server}", "{database}", '
        f'[Query="{escaped}"])\n'
        "in\n"
        "    Source"
    )
    return {"name": _safe_name(question, index), "question": question, "script": script}


def build_export(dashboard: dict) -> dict:
    """Turn a generated dashboard into Power BI artifacts.

    Only widgets that have SQL are included — a skipped or empty widget means
    nothing in an export, and shipping it as an empty query would produce a broken
    table in Power BI.
    """
    queries = [
        build_m_script(w["question"], w["sql"], i + 1)
        for i, w in enumerate(dashboard.get("widgets", []))
        if w.get("sql")
    ]

    return {
        "title": dashboard.get("title", "Dashboard"),
        "pbids": build_pbids(),
        "queries": queries,
        "instructions": [
            "Download the .pbids file and open it — Power BI Desktop will prompt "
            "for the database credentials. They are never written into the file.",
            "For each query below, use Home > Transform data > New Source > Blank "
            "Query, then Advanced Editor, and paste the script.",
            "The queries run against the same database in DirectQuery mode, so the "
            "Power BI report stays live rather than becoming a snapshot.",
        ],
        "note": (
            "This is an export, not a Power BI service integration. Publishing "
            "directly to a workspace would need an Azure AD app registration and "
            "tenant permissions this project does not have."
        ),
    }
