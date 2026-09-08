"""Asking questions, and approving the writes they sometimes produce.

These two endpoints belong together because they are two halves of one turn: a
destructive statement pauses `/query`, and `/approve` is what finishes it.
"""

from fastapi import APIRouter, HTTPException

from app.api.models import ApprovalRequest, QueryRequest, QueryResponse
from app.checkpointer import get_checkpointer
from app.graph import resume_agent, run_agent

router = APIRouter()


def _to_response(result: dict, thread_id: str | None) -> QueryResponse:
    """Agent state to API shape. Both endpoints return the same thing."""
    return QueryResponse(
        question=result["question"],
        sql_query=result["sql_query"],
        final_answer=result["final_answer"],
        logs=result["logs"],
        retry_count=result["retry_count"],
        thread_id=thread_id,
        awaiting_approval=result.get("approval_status") == "pending",
        guardrail_flags=result.get("guardrail_flags") or [],
        result_rows=result.get("result_rows") or [],
        row_count=result.get("row_count") or 0,
        memory_active=bool(thread_id and get_checkpointer() is not None),
    )


@router.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    result = run_agent(request.question, thread_id=request.thread_id)
    return _to_response(result, request.thread_id)


@router.post("/approve", response_model=QueryResponse)
def approve(request: ApprovalRequest) -> QueryResponse:
    """Resumes a conversation paused at the approval gate.

    409 when this thread is not waiting on a decision — a double-click, or a
    stale tab whose conversation finished long ago. That is neither the caller's
    fault nor a server failure, so neither 400 nor 500. Returning 200 quietly
    would be the worst of the three: the user would believe their decision was
    applied when nothing happened.
    """
    result = resume_agent(request.thread_id, request.approved)
    if result is None:
        raise HTTPException(
            status_code=409,
            detail="This conversation is not waiting for an approval decision.",
        )
    return _to_response(result, request.thread_id)
