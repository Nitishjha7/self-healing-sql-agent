"""FastAPI application: setup, middleware, router mounting, static files.

Endpoints live in `app/api/`. What stays here is the application itself — the
things that are true of every request rather than of one route.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import conversations, insights, query
from app.db import init_db
from app.ratelimit import rate_limit_middleware


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create and seed the tables, then serve.

    This replaces `@app.on_event("startup")`, which newer FastAPI deprecates —
    and MCP required moving to fastapi 0.141. The shutdown side is deliberately
    empty: the checkpointer's connection pool and the MCP bridge are both daemons
    and end with the process.
    """
    init_db()
    yield


app = FastAPI(title="PRISM INTEL — Self-Healing AI Data Agent", lifespan=lifespan)

# Local dev serves the frontend through nginx on the same origin, and the
# single-service image serves it from this app — neither needs CORS. Only a
# split deployment does, and then it should name the frontend origin rather
# than keep the wildcard.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", "*").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

app.middleware("http")(rate_limit_middleware)

# Everything the SPA calls lives under /api so it never collides with a static
# file path once the built frontend is mounted at "/".
api = APIRouter(prefix="/api")


@api.get("/health")
def api_health() -> dict:
    return {"status": "ok"}


api.include_router(query.router)
api.include_router(conversations.router)
api.include_router(insights.router)
app.include_router(api)


# Also at the root, because platform health checks and uptime pingers expect a
# plain /health. Kept out of the rate limiter for the same reason.
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# Mounted last: a mount at "/" swallows every path below it, so the API routes
# above must already be registered. Only present in the single-service image;
# under docker-compose nginx serves the frontend and this directory is absent.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
