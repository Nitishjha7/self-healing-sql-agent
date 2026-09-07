"""MCP server jo is project ka database tools ke roop me expose karta hai.

**Ye alag process me chalta hai**, agent ke saath stdio pipe se baat karta hai.
Isi baat ka poora point hai: data access ab agent ke andar `import` ki hui cheez
nahi, ek **protocol ke peeche baithi hui service** hai. Usi agent ko kal kisi aur
MCP server se joda ja sakta hai — GitHub, filesystem, kisi doosre database — bina
agent ka ek line badle. Aur ye server bhi kisi doosre MCP client (Claude Desktop,
koi IDE) se use ho sakta hai, kyunki interface standard hai, hamara khud ka
banaya hua nahi.

Chalane ke liye:  python -m mcp_server.server
Agent ise khud subprocess ki tarah start karta hai — dekho `app/mcp_client.py`.
"""

from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from app.db import get_schema_description, run_sql, run_write

# MCP SDK 2.x me `FastMCP` ka naam `MCPServer` ho gaya. Ye pehli koshish me toota
# tha, aur wo failure achhi tarah dikhi: client ne fallback lete hue direct
# driver use kar liya aur wajah log kar di — bilkul waisa hi jaisa design kiya
# tha. Ek chup-chaap fail hone wala MCP path sabse kharaab nateeja hota.
mcp = MCPServer("sql-agent-db")


@mcp.tool()
def describe_schema() -> str:
    """Return a plain-text description of the database schema.

    Includes example values and the relationship between tables, which raw DDL
    does not carry.
    """
    return get_schema_description()


@mcp.tool()
def run_select(query: str) -> str:
    """Execute a read-only SELECT query and return the rows as JSON.

    Errors are returned rather than raised, because the caller is an agent that
    repairs its own SQL from the error text — a transport-level exception would
    lose the very message it needs.
    """
    try:
        rows = run_sql(query)
    except Exception as exc:  # noqa: BLE001 — the message is the product here
        return json.dumps({"ok": False, "error": str(exc)})
    return json.dumps({"ok": True, "rows": _jsonable(rows), "row_count": len(rows)})


@mcp.tool()
def run_modify(query: str, commit: bool = False) -> str:
    """Execute a data-modifying statement, returning the affected row count.

    `commit=False` runs the statement and rolls it back — Postgres still plans it
    and enforces every constraint, so the count is real.

    **This tool carries no authority of its own.** Whether it may be called at
    all is decided upstream by the approval gate; the server does not know who
    approved anything. A tool that enforced its own policy would put that
    decision in two places at once, and the two would drift.
    """
    try:
        affected = run_write(query, commit=commit)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"ok": False, "error": str(exc)})
    return json.dumps({"ok": True, "affected": affected, "committed": commit})


def _jsonable(rows: list) -> list:
    """Postgres types that json.dumps refuses (Decimal, date) into plain values."""
    from datetime import date, datetime
    from decimal import Decimal

    def clean(v):
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        if v is None or isinstance(v, (str, int, float, bool)):
            return v
        return str(v)

    return [{k: clean(v) for k, v in row.items()} for row in rows]


if __name__ == "__main__":
    # stdio transport: the client spawns this process and speaks JSON-RPC over
    # its pipes. No port, no network surface, and the server's lifetime is tied
    # to the process that needs it.
    mcp.run(transport="stdio")
