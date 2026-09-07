"""Per-IP sliding-window rate limiter.

The public demo runs on a free Gemini tier — roughly 15 requests per minute for
the whole project, shared across every visitor. One bot, or one enthusiastic
visitor firing twenty questions, exhausts it and everyone after them sees an
error. Rate limiting is therefore not polish here: without it the demo breaks
itself.

Deliberately in-memory: a dict of deques, no Redis, no dependency. That is the
right call for a single-container demo and the wrong call for anything
multi-replica, because each process would keep its own counters. The fix at that
point is a shared store, not a bigger dict.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

MAX_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "5"))
WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))

# Paths that cost an LLM call. Both /health routes stay free so uptime pingers and the
# platform's own health checks are never throttled.
# /api/approve bhi yahan hai: resume ek synthesis LLM call chalata hai, to wo
# bhi utna hi quota kharch karta hai jitna ek naya sawaal.
# /api/dashboard yahan sabse zaroori hai: wo ek request me MAX_WIDGETS agent runs
# chalata hai, matlab ek call me 6-9 LLM calls.
LIMITED_PATHS = {"/api/query", "/api/approve", "/api/dashboard"}

_hits: dict[str, deque[float]] = defaultdict(deque)

# Without a ceiling this dict grows once per unique IP forever. Demo traffic is
# small, but an unbounded dict fed by user-controlled keys is a memory leak with
# extra steps.
MAX_TRACKED_IPS = 10_000


def _client_ip(request: Request) -> str:
    """Real client IP, accounting for the proxy in front of us.

    Cloud Run, Cloudflare and nginx all terminate the connection themselves, so
    request.client.host is the proxy. X-Forwarded-For's first entry is the
    original client. It is spoofable in general, but the platforms above
    overwrite it, and the downside of getting it wrong here is a demo throttling
    the wrong visitor — not a security boundary.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _prune(bucket: deque[float], now: float) -> None:
    while bucket and now - bucket[0] >= WINDOW_SECONDS:
        bucket.popleft()


async def rate_limit_middleware(request: Request, call_next):
    if request.url.path not in LIMITED_PATHS:
        return await call_next(request)

    now = time.monotonic()
    ip = _client_ip(request)
    bucket = _hits[ip]
    _prune(bucket, now)

    if len(bucket) >= MAX_REQUESTS:
        retry_after = int(WINDOW_SECONDS - (now - bucket[0])) + 1
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={
                "detail": (
                    f"Rate limit reached ({MAX_REQUESTS} questions per "
                    f"{WINDOW_SECONDS}s). This demo runs on a free LLM tier that "
                    f"is shared by everyone — try again in {retry_after}s."
                )
            },
        )

    bucket.append(now)

    if len(_hits) > MAX_TRACKED_IPS:
        for stale_ip in [k for k, v in _hits.items() if not v]:
            del _hits[stale_ip]

    return await call_next(request)
