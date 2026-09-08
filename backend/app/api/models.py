"""Request and response shapes for the API.

Kept apart from the routers because these are the contract — the thing a client
depends on — while the routers are just wiring. Several fields here exist to
report something the caller could otherwise only guess at, and each carries the
reason in its docstring: `awaiting_approval`, `memory_active` and
`guardrail_flags` all describe state that would be invisible and misleading if
inferred from an empty answer.
"""

from pydantic import BaseModel


class QueryRequest(BaseModel):
    question: str
    thread_id: str | None = None
    """Conversation id. Bhejo to agent pichhle turns yaad rakhta hai.

    Client generate karta hai, server nahi — server-generated session id ka
    matlab hota cookies/session state, aur ek stateless API me wo bewajah ka
    bojh hai. Bina `thread_id` ke API bilkul pehle jaisa stateless behave karti
    hai, to purane clients bina badle chalte rehte hain.
    """


class ApprovalRequest(BaseModel):
    thread_id: str
    approved: bool
    """Insaan ka faisla. `thread_id` yahan optional nahi hai.

    Approval hamesha ek rukhi hui conversation se judi hoti hai, aur wo
    conversation checkpointer me `thread_id` se hi mil sakti hai — bina uske
    approve karne ko kuch hai hi nahi.
    """


class QueryResponse(BaseModel):
    question: str
    sql_query: str
    final_answer: str
    logs: list[str]
    retry_count: int
    thread_id: str | None = None
    awaiting_approval: bool = False
    """Graph ek destructive query par ruka hua hai aur insaan ke faisle ka intezaar hai.

    Jab ye `true` ho, `final_answer` khaali hoti hai aur `sql_query` me wo
    statement hai jise approve karna hai. Client ko `/api/approve` call karna
    hoga — tab tak turn poora nahi hua. Ise ek alag flag banana zaroori tha:
    khaali `final_answer` apne aap me "kuch nahi mila" jaisa dikhta, jabki asal
    me system user ka jawab maang raha hai.
    """
    result_rows: list[dict] = []
    """Query ki rows table ke liye (50 tak)."""

    row_count: int = 0

    guardrail_flags: list[str] = []
    """Output guard ne kya pakda. Khaali = kuch nahi mila."""

    memory_active: bool = False
    """Kya is turn me sach me conversation memory chali.

    `thread_id` bhejne ka matlab ye nahi ki memory chal hi gayi — checkpointer
    setup fail ho sakta hai (DB down, permissions) aur agent chup-chaap stateless
    chalta rehta hai. Wo fallback jaan-boojh ke hai, par usko **chhupana** nahi
    chahiye: UI ko pata hona chahiye ki follow-up kaam karega ya nahi, warna user
    ko lagega agent bhool gaya jabki memory kabhi on hi nahi thi.
    """


class DashboardRequest(BaseModel):
    request: str
    thread_id: str | None = None
