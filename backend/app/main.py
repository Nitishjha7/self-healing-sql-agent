import os
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.checkpointer import get_checkpointer
from app.db import init_db
from app.graph import run_agent
from app.ratelimit import rate_limit_middleware

app = FastAPI(title="Self-Healing Data Query Agent")

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


class QueryResponse(BaseModel):
    question: str
    sql_query: str
    final_answer: str
    logs: list[str]
    retry_count: int
    thread_id: str | None = None
    memory_active: bool = False
    """Kya is turn me sach me conversation memory chali.

    `thread_id` bhejne ka matlab ye nahi ki memory chal hi gayi — checkpointer
    setup fail ho sakta hai (DB down, permissions) aur agent chup-chaap stateless
    chalta rehta hai. Wo fallback jaan-boojh ke hai, par usko **chhupana** nahi
    chahiye: UI ko pata hona chahiye ki follow-up kaam karega ya nahi, warna user
    ko lagega agent bhool gaya jabki memory kabhi on hi nahi thi.
    """


@app.on_event("startup")
def on_startup() -> None:
    init_db()


# Everything the SPA calls lives under /api so it never collides with a static
# file path once the built frontend is mounted at "/".
api = APIRouter(prefix="/api")


@api.get("/health")
def api_health() -> dict:
    return {"status": "ok"}


@api.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    result = run_agent(request.question, thread_id=request.thread_id)
    return QueryResponse(
        question=result["question"],
        sql_query=result["sql_query"],
        final_answer=result["final_answer"],
        logs=result["logs"],
        retry_count=result["retry_count"],
        thread_id=request.thread_id,
        memory_active=bool(request.thread_id and get_checkpointer() is not None),
    )


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
