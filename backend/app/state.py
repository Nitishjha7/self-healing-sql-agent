"""The agent's state schema.

Kept apart from `nodes.py` because these change for different reasons: the shape
changes when the agent gains a capability, node bodies change when its behaviour
is tuned. Settings live in `config.py` — those are neither shape nor behaviour.
"""

from typing import List, TypedDict


def _serializable(rows: list) -> list:
    """Turn Postgres types like Decimal and date into JSON-safe values.

    `Decimal` becomes `float` because it does not serialize to JSON directly, and
    anything else unrecognised becomes `str`. The checkpointer serializes these
    rows too, so an unhandled column type would break the API and conversation
    memory at the same time.
    """
    from datetime import date, datetime
    from decimal import Decimal

    def clean(v):
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        if v is None or isinstance(v, (str, int, float, bool)):
            return v
        return str(v)

    return [{k: clean(v) for k, v in row.items()} for row in rows]


class ConversationTurn(TypedDict):
    question: str
    sql_query: str
    answer: str


class AgentState(TypedDict):
    # --- per-turn: reset on every new question ------------------------------
    question: str
    sql_query: str
    query_result: str
    error: str
    retry_count: int
    final_answer: str
    logs: List[str]

    result_rows: List[dict]
    """The query's rows, for the UI table (up to `MAX_RESULT_ROWS`)."""

    row_count: int
    """How many rows actually came back — correct even when `result_rows` is capped."""

    guardrail_flags: List[str]
    """What the output guard caught this turn (an empty list means nothing).

    This goes out in the response. Redacting silently and moving on would make
    "the guard did something" and "the guard was never needed" look identical —
    and then there is no way to tell whether the guard works at all.
    """

    hitl_enabled: bool
    """Whether the approval gate is available on this turn.

    Interrupts need a checkpointer, so HITL only exists on the `thread_id` path.
    This flag carries that fact to `generate_sql`, because whether a gate exists
    decides whether the model may write a modifying statement at all.
    """

    approval_status: str
    """State of the HITL gate: `""` | `"pending"` | `"approved"` | `"rejected"`.

    Per-turn, not per-conversation — one turn's approval must not authorise the
    next turn's write. That would be the same bug as carrying `retry_count`
    forward, except the consequence is changed data.
    """

    # --- per-conversation: survives between turns ---------------------------
    history: List[ConversationTurn]
    """Prior turns, carried across by the checkpointer.

    **Once a checkpointer exists, every field needs a declared scope.** Without
    memory each invocation started from an empty state, so the question never
    arose. Now state survives between turns — and if `retry_count` or `logs`
    survived too, a previous turn's two retries would push the next question
    straight to "give up", and the trace would show the wrong question's steps.

    So `run_agent` explicitly resets every field above on each new question and
    leaves only `history` to be restored. That single decision is the difference
    between a memory feature and a memory bug.

    There is deliberately **no** additive reducer (`Annotated[..., operator.add]`):
    nodes return `{**state, ...}`, so each one already returns the whole history,
    and an additive reducer would re-append it at every node and grow the list
    exponentially. With overwrite semantics exactly one place appends exactly one
    turn — `synthesize_and_validate`.
    """
