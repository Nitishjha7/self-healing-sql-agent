"""Conversations list karna, kholna aur delete karna.

**Ye ek asli bug theek karta hai, feature nahi jodta.** Conversation memory Phase 4
me bani aur kaam bhi karti thi — par UI har page load pe naya `thread_id` banata
tha. Matlab har purani conversation Postgres me **padi rehti thi aur pahunch se
bahar ho jaati thi**. Data delete nahi ho raha tha, orphan ho raha tha. Bahar se
"refresh pe sab gayab" dikhta tha; andar se ye ek memory feature tha jo apne hi
checkpoints kabhi dobara nahi dhoondhta tha.

**Do alag raaste, jaan-boojh ke:**

- **Thread list SQL se** — `checkpoints` table se sirf `thread_id` aur timestamp.
  Sasta hai aur koi deserialization nahi.
- **Har thread ka content checkpointer ke API se** — pehla version blobs ko
  seedha SQL se padhne ki koshish karta tha, aur wo **galat approach thi**:
  LangGraph channel values ko `checkpoint_blobs` me **msgpack** me rakhta hai,
  jsonb me nahi. Use haath se decode karna ek andaruni format ko copy karna hota,
  jo agli library release me chup-chaap toot jaata. Checkpointer khud jaanta hai
  ki usne kya likha tha — usi se poochhna chahiye.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text

from app.checkpointer import get_checkpointer
from app.db import engine

log = logging.getLogger(__name__)

MAX_CONVERSATIONS = 40


def _tables_exist(conn) -> bool:
    """Checkpointer kabhi chala hi na ho to `checkpoints` table hoti hi nahi."""
    return bool(conn.execute(text("SELECT to_regclass('public.checkpoints')")).scalar())


def _thread_ids(limit: int) -> list[str]:
    """Thread ids, sabse haal wali pehle.

    `checkpoint->>'ts'` par sort karte hain, `thread_id` par nahi. Thread id me
    timestamp hota to hai, par wo **client banata hai** — ek alag client alag
    format bhej de to ordering chup-chaap galat ho jaati. `ts` server ka likha
    hua hai.
    """
    try:
        with engine.connect() as conn:
            if not _tables_exist(conn):
                return []
            rows = conn.execute(
                text(
                    "SELECT thread_id, MAX(checkpoint->>'ts') AS ts "
                    "FROM checkpoints GROUP BY thread_id "
                    "ORDER BY ts DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()
        return [r[0] for r in rows]
    except Exception as exc:  # noqa: BLE001 — DB down; sidebar degrades, app lives
        log.warning("Could not list conversation threads (%s).", exc)
        return []


def _history(thread_id: str) -> list:
    """Ek thread ki history, checkpointer ke apne deserializer se."""
    saver = get_checkpointer()
    if saver is None:
        return []
    try:
        tup = saver.get_tuple({"configurable": {"thread_id": thread_id}})
    except Exception as exc:  # noqa: BLE001 — one unreadable thread must not kill the list
        log.warning("Could not read conversation %s (%s).", thread_id, exc)
        return []

    if tup is None:
        return []
    history = (tup.checkpoint or {}).get("channel_values", {}).get("history")
    return history if isinstance(history, list) else []


def list_conversations(limit: int = MAX_CONVERSATIONS) -> list[dict]:
    """Saved conversations, naya pehle.

    Har thread ka ek checkpoint read hota hai — 40 threads pe 40 chhote reads.
    Ek sidebar ke liye theek hai; hazaaron conversations par ye ek alag summary
    table maangta, kyunki tab har page load pe poori list deserialize karna bewajah
    ka kharcha ban jaata.
    """
    conversations = []
    for thread_id in _thread_ids(limit):
        history = _history(thread_id)
        if not history:
            # Ek thread jisme koi poora turn nahi hua — user ne kuch poocha aur
            # jawab aane se pehle chala gaya. Ise list me dikhana matlab ek aisi
            # conversation offer karna jisme kuch hai hi nahi.
            continue
        conversations.append(
            {
                "thread_id": thread_id,
                "title": (history[0].get("question") or "Untitled")[:80],
                "turns": len(history),
            }
        )
    return conversations


def get_conversation(thread_id: str) -> Optional[dict]:
    """Ek conversation ke saare turns — reload ke baad transcript dobara banane ke liye."""
    history = _history(thread_id)
    if not history:
        return None
    return {"thread_id": thread_id, "turns": history}


def delete_conversation(thread_id: str) -> bool:
    """Ek conversation ke saare checkpoints hata deta hai.

    Teeno tables se hataana padta hai — sirf `checkpoints` saaf karne se
    `checkpoint_writes` aur `checkpoint_blobs` me orphan rows reh jaati hain, aur
    wahi haalat dobara ban jaati hai jo is file ne theek ki: data jo maujood hai
    par pahunch se bahar.
    """
    try:
        with engine.begin() as conn:
            if not _tables_exist(conn):
                return False
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                conn.execute(
                    text(f"DELETE FROM {table} WHERE thread_id = :tid"),  # noqa: S608
                    {"tid": thread_id},
                )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not delete conversation %s (%s).", thread_id, exc)
        return False
