# Self-Healing Data Query Agent

A natural-language-to-SQL agent that autonomously detects and self-heals from SQL syntax/schema errors using a cyclical LangGraph state machine, then validates its own output before returning it to the user.

Most Text-to-SQL demos are a single LLM call: if the generated SQL is wrong, the user gets a stack trace. This agent feeds the **actual database error back into the model** and regenerates the query — up to 3 times — before giving up gracefully.

## Tech Stack

| Layer | Technology |
|---|---|
| Agent Workflow | LangGraph (Python) — `StateGraph` with conditional edges |
| LLM Inference | LangChain + Google Gemini 2.0 Flash (`temperature=0`) |
| Output Safety | Prompt-level guardrails today; Guardrails AI planned (see Status) |
| Observability | LangSmith tracing (opt-in via env vars, off by default) |
| API Backend | FastAPI + Uvicorn |
| Data Store | PostgreSQL 16 (SQLAlchemy Core + psycopg2) |
| Frontend UI | React + Vite *(not built yet)* |
| Containerization | Docker & Docker Compose |

## How it works

1. User asks a question in natural language (e.g. "Who earns more than 80000 in Engineering?").
2. `generate_sql` builds a `SELECT` query from a plain-text schema description injected into the prompt.
3. `execute_sql` first blocks any destructive keyword (`DROP`/`DELETE`/`UPDATE`/`INSERT`/`ALTER`/`TRUNCATE`), then runs the query against PostgreSQL.
4. A **conditional edge** routes on the result:
   - success → synthesize
   - error and `retry_count < 3` → back to `generate_sql`, this time with the previous SQL **and** the database error in the prompt
   - error and retries exhausted → synthesize a graceful apology instead of leaking the traceback
5. `synthesize_and_validate` turns rows into a one-or-two-sentence answer, under a system prompt that forbids revealing raw table/column names.
6. The API returns the answer, the executed SQL, `retry_count`, and step-by-step trace logs for the UI.

See [docs/TECHNICAL_SPEC.md](docs/TECHNICAL_SPEC.md) for the architecture and state schema, [docs/CODE_NOTES.md](docs/CODE_NOTES.md) for why each file/dependency exists, and [docs/INTERVIEW_NOTES.md](docs/INTERVIEW_NOTES.md) for the pitch, trade-offs, and anticipated Q&A.

## Implementation Status

Honest snapshot — docs describe what exists, roadmap items are marked as such.

- ✅ `backend/app/db.py` — Postgres engine, `employees` table, seed data, `run_sql`
- ✅ `backend/app/graph.py` — full LangGraph self-healing state machine
- ✅ `backend/app/main.py` — `GET /health`, `POST /query`
- ✅ Docker Compose (`db` + `backend` + `frontend`)
- ✅ LangSmith tracing wired (opt-in; set `LANGCHAIN_TRACING_V2=true` + an API key)
- ✅ Two-table schema — `departments` + `employees` with a foreign key, so questions require real JOINs
- ✅ Evaluation harness — 20 questions with gold SQL, execution-accuracy metric, retries-on vs retries-off comparison ([eval/](eval/))
- ⬜ Guardrails AI validator layer (currently prompt-level safety only)
- ⬜ React chat UI (`frontend/` has only a Dockerfile)
- ⬜ Deployment (Neon + Render + Vercel)

## Project Structure

```
backend/    FastAPI app, LangGraph agent
frontend/   React + Vite chat UI (scaffold only)
docs/       Setup guide, technical spec, code notes, roadmap, interview notes
```

## Setup

```bash
cp .env.example .env   # fill in GOOGLE_API_KEY
docker compose up --build
```

This brings up three containers: `db` (PostgreSQL 16), `backend` (FastAPI + agent on :8000), and `frontend` (React via Nginx on :80). Swagger docs at `http://localhost:8000/docs`.

See [docs/SETUP.md](docs/SETUP.md) for the git/repo setup steps that were actually run.

## Roadmap

Near-term priorities are in [docs/ROADMAP.md](docs/ROADMAP.md). Longer term:

- **Phase 2**: Model Context Protocol (MCP) — talk to the database through a Postgres MCP server over stdio instead of a direct driver.
- **Phase 3**: Human-in-the-Loop (HITL) approval for destructive queries, replacing the current hard block.
- **Phase 4**: Postgres checkpointer for cross-session memory and multi-tenant isolation.

## Positioning

Part of an **"Agentic Self-Correcting Systems"** portfolio theme alongside [Adaptive CRAG](../adaptive-crag) and [Code Guardian](../code-guardian) — same underlying idea (LLM + self-verification + autonomous correction) applied to three different failure domains: SQL *execution errors*, retrieval *relevance*, and code *defects*.
