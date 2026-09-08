"""Listing, reopening and deleting saved conversations.

These exist because conversation memory was invisible without them: state was
being checkpointed correctly, but the UI generated a fresh `thread_id` on every
page load and could never find any of it again.
"""

from fastapi import APIRouter, HTTPException

from app.conversations import delete_conversation, get_conversation, list_conversations

router = APIRouter(prefix="/conversations")


@router.get("")
def conversations() -> dict:
    """Saved conversations, newest first. Outside the rate limiter — no LLM call."""
    return {"conversations": list_conversations()}


@router.get("/{thread_id}")
def conversation(thread_id: str) -> dict:
    """One conversation's turns, for rebuilding a transcript after a reload."""
    found = get_conversation(thread_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such conversation.")
    return found


@router.delete("/{thread_id}")
def remove_conversation(thread_id: str) -> dict:
    """Removes every checkpoint belonging to a conversation."""
    if not delete_conversation(thread_id):
        raise HTTPException(
            status_code=500, detail="Could not delete that conversation."
        )
    return {"deleted": thread_id}
