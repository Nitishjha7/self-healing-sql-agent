import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.checkpointer import get_checkpointer
from app.db import get_schema_overview, get_stats, init_db
from app.graph import resume_agent, run_agent
from app.ratelimit import rate_limit_middleware

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Tables banao/seed karo, phir serve karo.

    `@app.on_event("startup")` ki jagah — wo FastAPI ke naye versions me
    deprecated hai, aur MCP ke liye fastapi 0.141 pe jaana pada. Shutdown side
    jaan-boojh ke khaali hai: checkpointer ka connection pool aur MCP bridge
    dono daemon hain aur process ke saath hi khatam ho jaate hain.
    """
    init_db()
    yield


app = FastAPI(title="Self-Healing Data Query Agent", lifespan=lifespan)

# Local dev serves the frontend through nginx on the same origin, and the
# single-service image serves it from this app — neither needs CORS. Only a
# split deployment does, and then it should name the frontend origin rather
# than keep the wildcard.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", "*").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.middleware("http")(rate_limit_middleware)


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


# Everything the SPA calls lives under /api so it never collides with a static
# file path once the built frontend is mounted at "/".
api = APIRouter(prefix="/api")


@api.get("/health")
def api_health() -> dict:
    return {"status": "ok"}


def _to_response(result: dict, thread_id: str | None) -> QueryResponse:
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


@api.get("/schema")
def schema() -> dict:
    """Schema Explorer: columns, row counts, aur wahi text jo model ko jaata hai."""
    return get_schema_overview()


@api.get("/stats")
def stats() -> dict:
    """Dashboard aggregates. Rate limiter se bahar — koi LLM call nahi hoti."""
    return get_stats()


@api.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    result = run_agent(request.question, thread_id=request.thread_id)
    return _to_response(result, request.thread_id)


@api.post("/approve", response_model=QueryResponse)
def approve(request: ApprovalRequest) -> QueryResponse:
    """Approval gate par ruki hui conversation ko aage badhata hai.

    409 tab jab ye thread approval ka intezaar hi nahi kar raha — do baar
    approve dabana, ya ek purana tab jiski conversation kab ki poori ho chuki.
    Ye caller ki galti nahi hai aur na hi server ki kharabi; isliye na 400 na
    500. Chup-chaap 200 lauta dena sabse bura hota — user ko lagta uska faisla
    laga diya gaya, jabki kuch hua hi nahi.
    """
    result = resume_agent(request.thread_id, request.approved)
    if result is None:
        raise HTTPException(
            status_code=409,
            detail="This conversation is not waiting for an approval decision.",
        )
    return _to_response(result, request.thread_id)


app.include_router(api)


# Also at the root, because platform health checks and uptime pingers expect a
# plain /health. Kept out of the rate limiter for the same reason.
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# Mounted last: a mount at "/" swallows every path below it, so the API routes
# above must already be registered. Only present in the single-service image;
# under docker-compose nginx serves the frontend and this directory is absent.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
