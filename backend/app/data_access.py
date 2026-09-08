"""The single place through which the agent reaches the database.

There are two routes and they look identical from outside:

- **direct** — import `app.db` and call the driver straight
- **mcp** — run an MCP server as a subprocess and call its tools

`graph.py` does not care which one is active. That is the entire point of this
layer: the Phase 2 claim was that "data access moves from hard-wired code to a
swappable tool", and that claim is only true if the caller never has to change.

**Errors must look the same on both routes.** The self-healing loop runs on
Postgres error text — `column "emp_name" does not exist ... HINT: ...` — so the
MCP route must not lose that message by wrapping it in a transport exception.
The server returns the error in the payload, and this layer turns it back into
the same exception the direct route would raise. Without that, switching MCP on
would silently stop self-healing from working.
"""

from __future__ import annotations

import json

from app import db
from app.mcp_client import get_client


class DataAccessError(RuntimeError):
    """The database rejected the query. This message is what the retry prompt sees."""


def mode() -> str:
    """`"mcp"` or `"direct"` — shown in the trace and the UI."""
    return "mcp" if get_client() is not None else "direct"


def get_schema_description() -> str:
    client = get_client()
    if client is None:
        return db.get_schema_description()

    return client.call("describe_schema", {})


def run_sql(query: str) -> list[dict]:
    client = get_client()
    if client is None:
        return db.run_sql(query)

    result = json.loads(client.call("run_select", {"query": query}))
    if not result.get("ok"):
        # Postgres's message back into an exception, so that the `except` block
        # in `execute_sql` behaves identically on both routes.
        raise DataAccessError(result.get("error", "query failed"))
    return result["rows"]


def run_write(query: str, commit: bool) -> int:
    client = get_client()
    if client is None:
        return db.run_write(query, commit=commit)

    result = json.loads(client.call("run_modify", {"query": query, "commit": commit}))
    if not result.get("ok"):
        raise DataAccessError(result.get("error", "statement failed"))
    return result["affected"]
