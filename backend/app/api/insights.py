"""Read-only views over the system and its data, plus dashboard generation.

Grouped by what the caller gets rather than by cost: `/meta`, `/schema` and
`/stats` are cheap reads, `/dashboard` runs several full agent turns, and
`/dashboard/export` reshapes something the client already holds. Only the
expensive one is rate limited, and that is decided in `ratelimit.py` rather than
here.
"""

import logging

from fastapi import APIRouter

from app import config, data_access, ratelimit
from app.api.models import DashboardRequest
from app.checkpointer import get_checkpointer
from app.dashboard import build_dashboard
from app.db import get_schema_overview, get_server_version, get_stats
from app.powerbi import build_export

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/meta")
def meta() -> dict:
    """What this instance is actually running right now.

    Every field is read from the live process instead of being written into the
    UI. That is the whole reason this endpoint exists: the status bar it feeds
    replaced a row of fixed feature claims, and a claim that cannot go out of
    date is a claim that was never checked. These values change when the
    deployment changes — `USE_MCP`, `ALLOW_WRITES` and `MAX_RETRIES` are all
    env-driven, and the checkpointer can fail to start on any given boot.

    Nothing here is secret: it is the same information the docs state openly,
    and showing it is what lets a reader tell a demo in safe mode apart from one
    that is committing writes.
    """
    try:
        database = f"PostgreSQL {get_server_version()}"
    except Exception as exc:  # noqa: BLE001 — the bar should degrade, not vanish
        log.warning("Could not read the server version (%s).", exc)
        database = "PostgreSQL"

    return {
        "model": config.GEMINI_MODEL,
        "database": database,
        # "direct" or "mcp" — the toggle is the point of the data access layer.
        "data_access": data_access.mode(),
        "max_retries": config.MAX_RETRIES,
        # Named for what actually happens to an approved statement, because
        # "writes: off" would suggest it never runs — it does, then rolls back.
        "writes": "commit" if config.ALLOW_WRITES else "roll back",
        "memory": get_checkpointer() is not None,
        "rate_limit": f"{ratelimit.MAX_REQUESTS}/{ratelimit.WINDOW_SECONDS}s",
    }


@router.get("/schema")
def schema() -> dict:
    """Columns, row counts, and the exact text the model is given."""
    return get_schema_overview()


@router.get("/stats")
def stats() -> dict:
    """Dashboard aggregates. Outside the rate limiter — no LLM call."""
    return get_stats()


@router.post("/dashboard")
def dashboard(request: DashboardRequest) -> dict:
    """One sentence becomes several widgets, each a full agent run.

    This is inside the rate limiter and is `MAX_WIDGETS` times more expensive
    than a single question: one dashboard can cost 6-9 LLM calls. That is why the
    widget cap is four.
    """
    return build_dashboard(request.request, thread_id=request.thread_id)


@router.post("/dashboard/export")
def dashboard_export(dashboard: dict) -> dict:
    """Turns a generated dashboard into Power BI artifacts.

    Outside the rate limiter: no LLM call happens here, it only reshapes a
    dashboard the client already has.
    """
    return build_export(dashboard)
