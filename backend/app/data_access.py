"""Ek hi jagah jahan se agent database tak pahunchta hai.

Do raaste hain aur dono ek jaisa dikhte hain:

- **direct** — `app.db` ko import karke driver ko seedha bulao
- **mcp** — ek MCP server ko subprocess ki tarah chalao aur tools call karo

`graph.py` ko farak nahi padta ki kaunsa chal raha hai. Yahi is layer ka poora
maqsad hai: Phase 2 ka daawa ye tha ki "data access hard-wired code se badal kar
ek swappable tool ban jaaye", aur wo daawa tabhi sach hai jab caller ko badalna
hi na pade.

**Errors dono raaston me ek jaise aane chahiye.** Self-healing loop Postgres ke
error text par chalta hai — `column "emp_name" does not exist ... HINT: ...` — to
MCP raasta us message ko transport exception me lapet kar khota nahi. Server
error ko payload me bhejta hai, aur ye layer usko wapas usi exception me badal
deti hai jo direct raaste me uthti. Agar aisa na karein to MCP on karte hi
self-healing chup-chaap kaam karna band kar deta.
"""

from __future__ import annotations

from app import db
from app.mcp_client import get_client


class DataAccessError(RuntimeError):
    """Database ne query reject ki. Iska message hi retry prompt ko jaata hai."""


def mode() -> str:
    """`"mcp"` ya `"direct"` — trace aur UI me dikhane ke liye."""
    return "mcp" if get_client() is not None else "direct"


def get_schema_description() -> str:
    client = get_client()
    if client is None:
        return db.get_schema_description()

    result = client.call("describe_schema", {})
    # Ye tool plain text deta hai, JSON nahi — bridge ne use decode karne ki
    # koshish ki hogi aur str hi wapas mila hoga.
    return result if isinstance(result, str) else str(result)


def run_sql(query: str) -> list[dict]:
    client = get_client()
    if client is None:
        return db.run_sql(query)

    result = client.call("run_select", {"query": query})
    if not result.get("ok"):
        # Postgres ka message wapas ek exception me — taaki `execute_sql` ka
        # `except` block dono raaston me bilkul ek jaisa chale.
        raise DataAccessError(result.get("error", "query failed"))
    return result["rows"]


def run_write(query: str, commit: bool) -> int:
    client = get_client()
    if client is None:
        return db.run_write(query, commit=commit)

    result = client.call("run_modify", {"query": query, "commit": commit})
    if not result.get("ok"):
        raise DataAccessError(result.get("error", "statement failed"))
    return result["affected"]
