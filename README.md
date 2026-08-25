# Self-Healing Data Query Agent

A natural-language-to-SQL agent that autonomously detects and self-heals from SQL syntax/schema errors using cyclical LangGraph state machines, then validates its own output with Guardrails AI before returning it to the user.

## Tech Stack

| Layer | Technology |
|---|---|
| Agent Workflow | LangGraph (Python) |
| LLM Inference | LangChain / Groq (Llama 3.3 70B) |
| Output Validation | Guardrails AI |
| API Backend | FastAPI + Uvicorn |
| Data Store | PostgreSQL |
| Frontend UI | React + Vite |
| Containerization | Docker & Docker Compose |

## How it works

1. User asks a question in natural language (e.g. "Who earns more than 80000 in Engineering?").
2. The agent generates SQL against the known schema.
3. The query runs against PostgreSQL — on success, results flow to the synthesizer; on failure, the error is fed back into the agent and it retries (up to 3 times).
4. The final natural-language answer is checked by Guardrails AI for safety and schema-leakage before being returned.
5. The API response includes the answer, the executed SQL, and step-by-step trace logs for the UI.

See [docs/TECHNICAL_SPEC.md](docs/TECHNICAL_SPEC.md) for the full architecture, state schema, database schema, and roadmap.

## Project Structure

```
backend/    FastAPI app, LangGraph agent
frontend/   React + Vite chat UI
docs/       Setup guide and technical specification
```

## Setup

See [docs/SETUP.md](docs/SETUP.md) for git/repo setup steps.

```bash
docker compose up --build
```

This brings up three containers: `db` (PostgreSQL), `backend` (FastAPI + agent), and `frontend` (React via Nginx).

## Roadmap

- **Phase 2**: Model Context Protocol (MCP) — SQLite MCP Server over stdio.
- **Phase 3**: Human-in-the-Loop (HITL) approval for destructive queries.
- **Phase 4**: Postgres checkpointer for cross-session memory and multi-tenant isolation.
