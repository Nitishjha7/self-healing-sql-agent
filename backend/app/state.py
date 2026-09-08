"""The agent's state schema.

Kept apart from `nodes.py` because these change for different reasons: the shape
changes when the agent gains a capability, node bodies change when its behaviour
is tuned. Settings live in `config.py` — those are neither shape nor behaviour.
"""

from typing import List, TypedDict


def _serializable(rows: list) -> list:
    """Postgres ke Decimal/date jaise types ko JSON-safe banata hai.

    `Decimal` ko `float` me isliye badalte hain ki wo JSON me seedha nahi jaata,
    aur baaki anjaan types ko `str` — checkpointer bhi inhe serialize karta hai,
    to ek naya column type API aur memory dono ko ek saath todta.
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
    # --- per-turn: har naye sawaal pe reset hote hain -----------------------
    question: str
    sql_query: str
    query_result: str
    error: str
    retry_count: int
    final_answer: str
    logs: List[str]

    result_rows: List[dict]
    """Query ki rows, UI table ke liye (`MAX_RESULT_ROWS` tak)."""

    row_count: int
    """Kitni rows actually aayi — `result_rows` cap hone pe bhi sahi count."""

    guardrail_flags: List[str]
    """Output guard ne is turn me kya pakda (khaali list = kuch nahi).

    Response me jaata hai. Chup-chaap redact karke aage badhne ka matlab hota
    "guard ne kaam kiya" aur "guard ki kabhi zaroorat hi nahi padi" dono ek jaise
    dikhna — aur tab pata hi nahi chalta ki guard kaam kar raha hai ya nahi.
    """

    hitl_enabled: bool
    """Is turn me approval gate available hai ya nahi.

    Interrupt ke liye checkpointer chahiye, to HITL sirf `thread_id` wale path pe
    milta hai. Ye flag `generate_sql` tak wo baat pahunchata hai, kyunki gate hone
    ya na hone se ye badal jaata hai ki model ko write likhne di jaaye ya nahi.
    """

    approval_status: str
    """HITL gate ki haalat: `""` | `"pending"` | `"approved"` | `"rejected"`.

    Per-turn hai, per-conversation nahi — ek turn ki approval agle turn ki write
    ko authorize nahi karti. Wahi bug hoti jo `retry_count` ke saath hoti, bas
    isme nateeja data change hota.
    """

    # --- per-conversation: turns ke beech zinda rehte hain ------------------
    history: List[ConversationTurn]
    """Pichhle turns, checkpointer ke through carry hote hue.

    **Checkpointer aa jaane ke baad ye batana zaroori ho jaata hai ki kaunsi
    field kis scope ki hai.** Bina memory ke har invocation khaali state se
    shuru hoti thi, to sawaal uthta hi nahi tha. Ab state turns ke beech survive
    karti hai — aur agar `retry_count` ya `logs` bhi survive kar jaayein to
    pichhle turn ki do retries agle turn ko turant "give up" pe dhakel dengi,
    aur trace me pichhle sawaal ki lines dikhengi.

    Isliye `run_agent` har naye sawaal pe upar wali saari fields explicitly
    reset karta hai, aur `history` ko chhodta hai. Yahi ek line ye tay karti hai
    ki memory feature hai ya bug.

    Reducer (`Annotated[..., operator.add]`) jaan-boojh ke nahi lagaya: nodes
    `{**state, ...}` return karte hain, to har node poori history wapas bhejta
    hai — additive reducer use har baar dobara jod deta aur history exponentially
    badhti. Overwrite semantics ke saath sirf `synthesize_and_validate` isme ek
    turn add karta hai, ek hi jagah, ek hi baar.
    """

