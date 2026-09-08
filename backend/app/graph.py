"""Graph wiring and the two entry points the API calls.

What is here is only how the pieces connect: which node follows which, where the
interrupt sits, and how a run is started or resumed. The nodes themselves are in
`nodes.py`, the state they pass around is in `state.py`, the settings are in
`config.py`.

Splitting it out mattered because these change independently. Adding a node is a
wiring change; changing a prompt is not — and for a long time both meant editing
the same 646-line file.
"""

from typing import Optional

from langgraph.graph import END, StateGraph

from app.checkpointer import get_checkpointer
from app.nodes import (
    after_approval,
    await_approval,
    execute_sql,
    generate_sql,
    needs_approval,
    should_retry,
    synthesize_and_validate,
)
from app.state import AgentState


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("await_approval", await_approval)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("synthesize_and_validate", synthesize_and_validate)

    graph.set_entry_point("generate_sql")

    # A destructive query goes through the approval gate; everything else runs
    # straight through.
    graph.add_conditional_edges(
        "generate_sql",
        needs_approval,
        {"approval": "await_approval", "execute": "execute_sql"},
    )
    graph.add_conditional_edges(
        "await_approval",
        after_approval,
        {"execute": "execute_sql", "rejected": "synthesize_and_validate"},
    )
    graph.add_conditional_edges(
        "execute_sql",
        should_retry,
        {
            "retry": "generate_sql",
            "give_up": "synthesize_and_validate",
            "success": "synthesize_and_validate",
        },
    )
    graph.add_edge("synthesize_and_validate", END)

    # **Interrupts only exist with a checkpointer.** Pausing a LangGraph run and
    # resuming it later means the state has to be saved somewhere — without a
    # checkpointer `interrupt_before` means nothing. So the stateless graph keeps
    # the old hard block, and HITL is available only on the `thread_id` path.
    # That is a direct consequence of Phase 4 landing before Phase 3, not an
    # accident.
    if checkpointer is not None:
        return graph.compile(
            checkpointer=checkpointer, interrupt_before=["await_approval"]
        )
    return graph.compile()


# Cache of compiled graphs. Every request used to call `build_graph()`, which was
# merely wasteful without a checkpointer — with one it would be wrong, because a
# checkpointer holds a connection pool and opening a new pool per request leaks.
_graphs: dict = {}


def _get_graph(checkpointer=None):
    key = "memory" if checkpointer is not None else "stateless"
    if key not in _graphs:
        _graphs[key] = build_graph(checkpointer)
    return _graphs[key]


def run_agent(question: str, thread_id: Optional[str] = None) -> AgentState:
    """Run one question. Pass a `thread_id` to continue that conversation.

    Without a `thread_id` the behaviour is exactly what it was before —
    stateless, no memory. The eval harness and the tests take that path, and it
    is the right one for them: every eval question must be independent, or the
    answer to the first would change the score of the next.
    """
    checkpointer = get_checkpointer() if thread_id else None
    app = _get_graph(checkpointer)

    # **Every per-turn field is explicitly reset on a new question.** With a
    # checkpointer this is essential: LangGraph merges this dict over the
    # checkpointed state, so any key missing here carries over from the previous
    # turn. `history` is left out deliberately — that is the one thing that
    # should carry. Everything else must reset, or the last turn's retries would
    # push this question straight to "give up" and the trace would show the
    # previous question's steps.
    turn_input: dict = {
        "question": question,
        "sql_query": "",
        "query_result": "",
        "error": "",
        "retry_count": 0,
        "final_answer": "",
        "logs": [],
        # One turn's approval must not authorise the next turn's write.
        "approval_status": "",
        "guardrail_flags": [],
        "result_rows": [],
        "row_count": 0,
        # The gate exists only when a checkpointer does — an interrupt needs
        # somewhere to save state. This is what decides whether the model may
        # write a modifying statement at all.
        "hitl_enabled": checkpointer is not None,
    }

    if checkpointer is None:
        turn_input["history"] = []
        return app.invoke(turn_input)

    config = {"configurable": {"thread_id": thread_id}}
    result = app.invoke(turn_input, config=config)

    # If the graph stopped at the approval gate, `invoke` returns the state as of
    # that moment, with an empty `final_answer`. Treating that as "finished"
    # would be the most misleading outcome available: the caller gets a blank
    # answer and no hint that the system is waiting on their decision.
    if _is_awaiting_approval(app, config):
        return {**result, "approval_status": "pending"}
    return result


def _is_awaiting_approval(app, config) -> bool:
    """Whether the graph is paused just before the approval node.

    `state.next` names the node that will run next. After an interrupt that is
    `await_approval` — meaning the graph is standing at the gate, not through it.
    """
    try:
        snapshot = app.get_state(config)
    except Exception:  # noqa: BLE001 — checkpointer read fail; treat as not paused
        return False
    return "await_approval" in (snapshot.next or ())


def resume_agent(thread_id: str, approved: bool) -> Optional[AgentState]:
    """Carry a paused conversation forward with the human's decision.

    Returns `None` when this thread is not waiting for approval at all — for the
    caller that is a 409, not a 500: the request is not malformed, it just does
    not apply right now (approve pressed twice, or a stale tab).
    """
    checkpointer = get_checkpointer()
    if checkpointer is None:
        return None

    app = _get_graph(checkpointer)
    config = {"configurable": {"thread_id": thread_id}}

    if not _is_awaiting_approval(app, config):
        return None

    # Write the decision into state, then resume with no new input. `None` means
    # "continue from where you stopped" — passing fresh input would restart the
    # turn and spend another LLM call.
    app.update_state(
        config, {"approval_status": "approved" if approved else "rejected"}
    )
    return app.invoke(None, config=config)
