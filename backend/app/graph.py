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

    # Destructive query approval gate se hoke jaati hai, baaki seedha execute.
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

    # **Interrupt sirf checkpointer ke saath.** LangGraph ko pause karke baad me
    # resume karne ke liye state kahin save karni padti hai — bina checkpointer
    # ke `interrupt_before` ka koi matlab nahi. Isliye stateless graph purane
    # hard block pe chalta hai, aur HITL sirf `thread_id` wale path pe milta hai.
    # Ye Phase 4 ke Phase 3 se pehle aane ka seedha nateeja hai, ittefaq nahi.
    if checkpointer is not None:
        return graph.compile(
            checkpointer=checkpointer, interrupt_before=["await_approval"]
        )
    return graph.compile()


# Compiled graphs cache. Pehle har request `build_graph()` chalati thi, jo bina
# checkpointer ke sirf fizool tha — ab galat bhi hota, kyunki checkpointer ke
# peeche connection pool hai aur har request pe naya pool kholna leak hai.
_graphs: dict = {}


def _get_graph(checkpointer=None):
    key = "memory" if checkpointer is not None else "stateless"
    if key not in _graphs:
        _graphs[key] = build_graph(checkpointer)
    return _graphs[key]


def run_agent(question: str, thread_id: Optional[str] = None) -> AgentState:
    """Ek sawaal chalao. `thread_id` do to wo conversation continue hoti hai.

    `thread_id` ke bina behaviour bilkul pehle jaisa hai — stateless, koi memory
    nahi. Eval harness aur tests isi path pe chalte hain, aur yahi unke liye sahi
    hai: har eval question independent hona chahiye, warna pehle sawaal ka jawab
    agle ka score badal dega.
    """
    checkpointer = get_checkpointer() if thread_id else None
    app = _get_graph(checkpointer)

    # **Har naye sawaal pe per-turn fields explicitly reset.** Checkpointer ke
    # saath ye zaroori hai: LangGraph is dict ko checkpointed state ke upar merge
    # karta hai, to jo key yahan nahi hai wo pichhle turn se aage carry hoti hai.
    # `history` jaan-boojh ke chhodi hai — usi ko carry hona chahiye. Baaki sab
    # reset hona chahiye, warna pichhle turn ki retries agle turn ko turant
    # "give up" pe dhakel dengi aur trace me purane sawaal ki lines dikhengi.
    turn_input: dict = {
        "question": question,
        "sql_query": "",
        "query_result": "",
        "error": "",
        "retry_count": 0,
        "final_answer": "",
        "logs": [],
        # Pichhle turn ki approval is turn ki write ko authorize na kar de.
        "approval_status": "",
        "guardrail_flags": [],
        "result_rows": [],
        "row_count": 0,
        # Gate tabhi hai jab checkpointer hai — interrupt ko state save karne ki
        # jagah chahiye. Isi se tay hota hai ki model write likh sakta hai ya nahi.
        "hitl_enabled": checkpointer is not None,
    }

    if checkpointer is None:
        turn_input["history"] = []
        return app.invoke(turn_input)

    config = {"configurable": {"thread_id": thread_id}}
    result = app.invoke(turn_input, config=config)

    # Agar graph approval gate pe ruka hai to `invoke` us waqt ki state lauta
    # deta hai, `final_answer` khaali. Ise "poora ho gaya" maan lena sabse
    # gumraah karne wala outcome hota: caller ko khaali jawab milta aur pata
    # bhi nahi chalta ki system uske faisle ka intezaar kar raha hai.
    if _is_awaiting_approval(app, config):
        return {**result, "approval_status": "pending"}
    return result


def _is_awaiting_approval(app, config) -> bool:
    """Graph approval node se pehle ruka hua hai ya nahi.

    `state.next` batata hai ki agla kaun sa node chalega. Interrupt ke baad wahan
    `await_approval` hota hai — matlab graph gate pe khada hai, andar nahi gaya.
    """
    try:
        snapshot = app.get_state(config)
    except Exception:  # noqa: BLE001 — checkpointer read fail; treat as not paused
        return False
    return "await_approval" in (snapshot.next or ())


def resume_agent(thread_id: str, approved: bool) -> Optional[AgentState]:
    """Ruki hui conversation ko insaan ke faisle ke saath aage badhata hai.

    `None` deta hai agar ye thread approval ka intezaar hi nahi kar raha —
    caller ke liye ye 409 hai, 500 nahi: request galat nahi hai, bas is waqt
    lagoo nahi hoti (do baar approve dabana, ya purana tab).
    """
    checkpointer = get_checkpointer()
    if checkpointer is None:
        return None

    app = _get_graph(checkpointer)
    config = {"configurable": {"thread_id": thread_id}}

    if not _is_awaiting_approval(app, config):
        return None

    # Faisla state me likho, phir bina naye input ke resume karo. `None` ka matlab
    # hai "jahan ruke the wahin se chalao" — naya input dene se turn dobara shuru
    # ho jaata aur ek aur LLM call lag jaati.
    app.update_state(
        config, {"approval_status": "approved" if approved else "rejected"}
    )
    return app.invoke(None, config=config)
