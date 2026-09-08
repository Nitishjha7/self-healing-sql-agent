"""An MCP server exposing this project’s database as tools.

**It runs in its own process** and talks to the agent over a stdio pipe. That is
the entire point: data access is no longer something the agent `import`s, it is a
**service behind a protocol**. The same agent could be pointed at a different MCP
server tomorrow — GitHub, a filesystem, another database — without changing a
line of the agent. And this server can equally be used by any other MCP client
(Claude Desktop, an IDE), because the interface is a standard one rather than
something we invented.

To run it:  python -m mcp_server.server
The agent starts it as a subprocess itself — see `app/mcp_client.py`.
"""

from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from app.db import get_schema_description, run_sql, run_write

# MCP SDK 2.x renamed `FastMCP` to `MCPServer`. This broke on the first attempt,
# and the failure showed up well: the client fell back to the direct driver and
# logged the reason — exactly as designed. An MCP path that failed silently would
# have been the worst outcome.
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
