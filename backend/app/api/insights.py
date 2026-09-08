"""Read-only views over the database, plus dashboard generation and export.

Grouped by what the caller gets rather than by cost: `/schema` and `/stats` are
plain queries, `/dashboard` runs several full agent turns, and
`/dashboard/export` reshapes something the client already holds. Only the middle
one is rate limited, and that is decided in `ratelimit.py` rather than here.
"""

from fastapi import APIRouter

from app.api.models import DashboardRequest
from app.dashboard import build_dashboard
from app.db import get_schema_overview, get_stats
from app.powerbi import build_export

router = APIRouter()


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
