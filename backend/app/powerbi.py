"""Phase 6 — generated dashboard ko Power BI me le jaana.

**Ye "Power BI integration" nahi hai, aur use aisa kehna galat hoga.** Power BI
service me dataset push karne ke liye ek Azure AD app registration, ek tenant, aur
workspace permissions chahiye — teeno cheezein is project ke paas nahi hain aur
ek portfolio demo ke liye honi bhi nahi chahiye.

Jo **ban sakta hai aur sach me kaam karta hai** wo export hai: do artifacts jo
Power BI Desktop seedha khol leta hai.

1. **`.pbids`** — Power BI ka apna data-source descriptor. Ise double-click karo,
   Desktop khud Postgres se connect karne ka prompt de deta hai. Credentials isme
   **kabhi nahi** jaate; Power BI unhe khud maangta hai aur apne credential store
   me rakhta hai.
2. **Power Query (M) script** har widget ke liye — usme wahi SQL hai jo agent ne
   generate ki thi. Advanced Editor me paste karo aur wo query ek table ban jaati
   hai.

Matlab jo dashboard agent ne banaya, wo Power BI me **live query** ban jaata hai,
ek jami hui CSV nahi — user wahan filters, relationships, apne visuals sab jod
sakta hai.
"""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse


def _connection() -> tuple[str, str]:
    """`DATABASE_URL` se host:port aur database name nikaalta hai.

    Username/password jaan-boojh ke chhod dete hain. Ye file user ko download
    hoti hai aur uske disk par rehti hai — usme credentials daalna wahi galti
    hai jo `.env.example` me API key daalna thi.
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
                    # DirectQuery isliye ki dashboard live rahe. Import mode ek
                    # snapshot bana deta, aur tab Power BI wala dashboard is
                    # database se chupchaap purana hota jaata.
                    "mode": "DirectQuery",
                }
            ],
        },
        indent=2,
    )


def _safe_name(question: str, index: int) -> str:
    """Question ko ek Power Query identifier me badalta hai.

    M me query names me spaces chalte hain par har jagah quote karne padte hain,
    aur duplicate names chup-chaap ek doosre ko overwrite kar dete hain — isliye
    index prefix hamesha lagta hai.
    """
    words = re.sub(r"[^A-Za-z0-9 ]", "", question).split()[:5]
    stem = "".join(w.capitalize() for w in words) or "Query"
    return f"Q{index}_{stem}"


def build_m_script(question: str, sql: str, index: int) -> dict:
    """Ek widget ke liye Power Query M.

    SQL ko M string literal me daalne se pehle escape karna zaroori hai: M me
    `"` ko `""` likha jaata hai. Bina iske ek `WHERE name = 'x'` wali query bhi
    theek chal jaati, par koi bhi double-quoted identifier script ko tod deta.
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
    """Generated dashboard ko Power BI artifacts me badalta hai.

    Sirf wahi widgets aate hain jinke paas SQL hai — skipped ya khaali widgets ka
    export me koi matlab nahi, aur unhe khaali query ki tarah bhejna Power BI me
    ek toota hua table bana deta.
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
