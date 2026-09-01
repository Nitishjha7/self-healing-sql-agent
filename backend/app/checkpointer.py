"""Postgres checkpointer — conversation state jo request ke baad bhi zinda rehti hai.

**Ye kyun, aur kyun Postgres:** har `/api/query` request ek naya process nahi,
par ek naya graph invocation zaroor hai. Bina checkpointer ke har invocation
khaali state se shuru hoti hai, to follow-up question ("unme se kitne Bangalore
me hain?") ka koi matlab hi nahi banta — agent ko pata hi nahi ki "unme se" kya.

`MemorySaver` bhi ye kaam kar deta, par sirf tab tak jab tak process zinda hai.
Render pe container 15 min me sota hai; user wapas aake follow-up poochta hai aur
conversation gayab. Postgres yahan already chal raha hai (isi ka to poora project
hai), to ek naya service add kiye bina durable checkpointing mil jaati hai.

**Optional by design.** `thread_id` ke bina agent bilkul pehle jaisa stateless
chalta hai — eval harness aur tests isi path pe chalte hain, aur unhe conversation
memory chahiye bhi nahi (har eval question independent hona chahiye). Agar Postgres
tak pahunch na ho to app crash nahi karti, memory chup-chaap off ho jaati hai:
ek chat app ka memory feature down hona ek cheez hai, poori app ka na chalna
doosri.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger(__name__)

_checkpointer = None
_tried = False


def get_checkpointer():
    """Process-wide `PostgresSaver`, ya `None` agar setup na ho paye.

    Ek hi baar banta hai: `PostgresSaver` ke peeche ek connection pool hai, aur
    har request pe naya pool kholna connection leak ka sabse seedha raasta hai.
    Failure bhi ek hi baar log hoti hai — warna har request ek stack trace likhti.
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
            # autocommit zaroori hai: PostgresSaver har checkpoint write ko apne
            # aap commit maanta hai. Iske bina writes ek khuli transaction me
            # latak jaate hain aur agli request unhe dekh hi nahi paati.
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=True,
        )
        saver = PostgresSaver(pool)
        # Tables banata hai agar nahi hain. Idempotent — har start pe safe.
        saver.setup()
        log.info("Postgres checkpointer ready — conversation memory is on.")
        _checkpointer = saver
    except Exception as exc:  # noqa: BLE001 — DB down, driver missing, permissions
        log.warning("Checkpointer setup failed (%s) — conversation memory is off.", exc)
        _checkpointer = None

    return _checkpointer


def reset_for_tests() -> None:
    """Cached checkpointer bhool jao — sirf tests ke liye."""
    global _checkpointer, _tried
    _checkpointer, _tried = None, False
