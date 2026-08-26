from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.db import init_db
from app.graph import run_agent

app = FastAPI(title="Self-Healing Data Query Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    question: str
    sql_query: str
    final_answer: str
    logs: list[str]
    retry_count: int


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    result = run_agent(request.question)
    return QueryResponse(
        question=result["question"],
        sql_query=result["sql_query"],
        final_answer=result["final_answer"],
        logs=result["logs"],
        retry_count=result["retry_count"],
    )
