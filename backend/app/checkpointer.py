"""Postgres checkpointer — conversation state that outlives a single request.

**Why this exists, and why Postgres:** every `/api/query` is not a new process,
but it is certainly a new graph invocation. Without a checkpointer each
invocation starts from empty state, so a follow-up question ("how many of them
are in Bangalore?") means nothing — the agent has no idea what "them" refers to.

`MemorySaver` would also do this, but only for as long as the process lives.
On Render the container sleeps after 15 minutes; the user comes back, asks a
follow-up, and the conversation is gone. Postgres is already running here (the
whole project is built around it), so durable checkpointing costs no extra
service.

**Optional by design.** Without a `thread_id` the agent runs exactly as it did
before — stateless. The eval harness and the tests take that path, and they do
not want conversation memory (every eval question must be independent). If
Postgres is unreachable the app does not crash; memory just switches off
quietly: a chat app losing its memory feature is one thing, the whole app
failing to start is another.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger(__name__)

_checkpointer = None
_tried = False


def get_checkpointer():
    """The process-wide `PostgresSaver`, or `None` if it could not be set up.

    Built once: a `PostgresSaver` holds a connection pool behind it, and opening
    a new pool per request is the most direct route to a connection leak. The
    failure is logged once too — otherwise every request would write a stack
    trace.
    """
    global _checkpointer, _tried

    if _tried:
        return _checkpointer
    _tried = True

    if os.environ.get("DISABLE_CHECKPOINTER", "").lower() in ("1", "true", "yes"):
        log.info("Checkpointer disabled by env — conversations will be stateless.")
        return None

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        log.warning("DATABASE_URL not set — conversation memory is off.")
        return None

    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(
            conninfo=dsn,
            max_size=int(os.environ.get("CHECKPOINTER_POOL_SIZE", "5")),
            # autocommit is required: PostgresSaver assumes each checkpoint write
            # commits itself. Without it, writes hang in an open transaction and
            # the next request never sees them.
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=True,
        )
        saver = PostgresSaver(pool)
        # Creates the tables if they are missing. Idempotent — safe on every start.
        saver.setup()
        log.info("Postgres checkpointer ready — conversation memory is on.")
        _checkpointer = saver
    except Exception as exc:  # noqa: BLE001 — DB down, driver missing, permissions
        log.warning("Checkpointer setup failed (%s) — conversation memory is off.", exc)
        _checkpointer = None

    return _checkpointer


def reset_for_tests() -> None:
    """Forget the cached checkpointer — for tests only."""
    global _checkpointer, _tried
    _checkpointer, _tried = None, False
