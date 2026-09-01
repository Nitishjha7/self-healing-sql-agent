# Self-Healing Data Query Agent

A natural-language-to-SQL agent that autonomously detects and self-heals from SQL syntax/schema errors using a cyclical LangGraph state machine, then validates its own output before returning it to the user.

Most Text-to-SQL demos are a single LLM call: if the generated SQL is wrong, the user gets a stack trace. This agent feeds the **actual database error back into the model** and regenerates the query — up to 3 times — before giving up gracefully.

## Tech Stack

| Layer | Technology |
|---|---|
| Agent Workflow | LangGraph (Python) — `StateGraph` with conditional edges |
| Conversation memory | LangGraph `PostgresSaver` checkpointer, keyed by `thread_id` |
| LLM Inference | LangChain + Google Gemini (`temperature=0`, model set via `GEMINI_MODEL`) |
| Output Safety | Prompt-level guardrails today; Guardrails AI planned (see Status) |
| Observability | LangSmith tracing (opt-in via env vars, off by default) |
| API Backend | FastAPI + Uvicorn |
| Data Store | PostgreSQL 16 (SQLAlchemy Core + psycopg2) |
| Frontend UI | React 18 + Vite, served by Nginx (`/api/` reverse proxy) |
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

If the request carried a `thread_id`, step 2 also receives the earlier turns of that
conversation, and step 5's answer is appended to them — see [Conversation memory](#conversation-memory).

See [docs/TECHNICAL_SPEC.md](docs/TECHNICAL_SPEC.md) for the architecture and state schema, [docs/CODE_NOTES.md](docs/CODE_NOTES.md) for why each file/dependency exists, and [docs/INTERVIEW_NOTES.md](docs/INTERVIEW_NOTES.md) for the pitch, trade-offs, and anticipated Q&A.

## Implementation Status

Honest snapshot — docs describe what exists, roadmap items are marked as such.

- ✅ `backend/app/db.py` — Postgres engine, `departments` + `employees` tables (FK), seed data, `run_sql`
- ✅ `backend/app/graph.py` — full LangGraph self-healing state machine
- ✅ `backend/app/main.py` — `GET /health`, `POST /query`
- ✅ Docker Compose (`db` + `backend` + `frontend`)
- ✅ LangSmith tracing wired (opt-in; set `LANGCHAIN_TRACING_V2=true` + an API key)
- ✅ Two-table schema — `departments` + `employees` with a foreign key, so questions require real JOINs
- ✅ Evaluation harness — 20 questions with gold SQL, execution-accuracy metric, retries-on vs retries-off comparison ([eval/](eval/))
- ✅ Conversation memory — LangGraph `PostgresSaver` checkpointer, per-`thread_id`, so follow-up questions can refer back ([how it works](#conversation-memory))
- ✅ Test suite — 10 tests covering the memory semantics, no API key or database needed
- ⬜ Guardrails AI validator layer (currently prompt-level safety only)
- ✅ React + Vite chat UI — answer bubbles, retry badge, collapsible SQL & execution trace, served by Nginx with an `/api/` proxy
- ✅ Deployment ready — single-service Docker image (FastAPI serves the API + built SPA on one URL), per-IP rate limiting, `render.yaml`, guide in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- ⬜ Actually deployed (no live URL yet) — remaining steps are checklisted at the top of [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

## Project Structure

```
Dockerfile  Single-service deploy image (React build + FastAPI)
backend/    FastAPI app, LangGraph agent, Postgres checkpointer, tests
frontend/   React + Vite chat UI, Nginx-served with an /api proxy
eval/       Evaluation harness, gold questions, measured results
docs/       Setup, technical spec, code notes, roadmap, interview notes, deployment
```

## Setup

```bash
cp .env.example .env   # fill in GOOGLE_API_KEY
docker compose up --build
```

This brings up three containers: `db` (PostgreSQL 16), `backend` (FastAPI + agent on :8000), and `frontend` (React via Nginx on :80). Open `http://localhost` for the chat UI; Swagger docs are at `http://localhost:8000/docs`.

If those ports are taken, set `BACKEND_PORT` / `FRONTEND_PORT` in `.env` — the compose file reads both.

## Conversation memory

Send a `thread_id` with a question and the agent remembers that conversation, so
follow-ups can refer back instead of restating the subject:

```bash
curl -X POST localhost:8000/api/query -H 'Content-Type: application/json' \
  -d '{"question":"Which department has the highest average salary?","thread_id":"demo-1"}'
# -> "The Engineering department has the highest average salary."

curl -X POST localhost:8000/api/query -H 'Content-Type: application/json' \
  -d '{"question":"How many people work there?","thread_id":"demo-1"}'
# -> SELECT COUNT(e.id) ... WHERE d.name = 'Engineering'   -> "There are currently 4 people working there."
```

**The same follow-up with no `thread_id` is the demo.** It does not error — it
answers confidently and wrongly:

```
SELECT COUNT(*) FROM employees   ->   "There are 10 people currently working there."
```

It silently dropped the word "there" and counted every employee in the company.
That is the failure mode memory removes, and it is worth showing precisely
because it does not look like a failure.

**Two pieces are required, and a checkpointer is only one of them.** The
checkpointer makes state durable across requests; it does nothing on its own to
help the model, because a model cannot read a checkpoint. The prior turns also
have to reach the prompt — `_format_history()` does that, and it sends each turn's
**SQL** as well as its English answer, since `ORDER BY AVG(e.salary) DESC LIMIT 1`
pins down what "them" refers to more precisely than a sentence does.

**Why Postgres rather than `MemorySaver`.** `MemorySaver` keeps state in the
process. The free tier this is deployed to sleeps after 15 minutes of inactivity,
so a user who returns and asks a follow-up would find the conversation gone.
Postgres is already in this stack, so durability costs no new service — verified
by restarting the backend container mid-conversation and continuing the same
thread, which still resolved "that department" correctly.

**What the checkpointer changed about state design.** Once state survives between
turns, every field needs a scope. `history` should carry over; `retry_count`,
`logs`, `error` and the rest must not — a previous turn's two retries would push
the next question straight to "give up", and its trace would show the wrong
question's steps. `run_agent()` resets the per-turn fields explicitly on every
call and leaves only `history` to be restored from the checkpoint. That single
decision is the difference between a memory feature and a bug, and it is what
four of the tests pin down.

Memory is optional and fails open: without a `thread_id` the agent is stateless
exactly as before (which is what the eval harness needs, so that one question's
answer cannot influence the next one's score), and if the checkpointer cannot
start, the API reports `memory_active: false` rather than pretending.

### Tests

```bash
docker build -f backend/Dockerfile.test -t sql-agent-test backend && docker run --rm sql-agent-test
```

10 tests, no API key and no database required — they cover history formatting,
the append-exactly-once rule, the per-turn reset invariant, and the stateless
fallback. The agent prompts themselves are not unit-tested; that is what
[eval/](eval/) measures.

### Measured results

The self-healing loop doubles accuracy (15% → 30%) when the schema description is
stale enough that queries actually fail, and contributes exactly nothing (95% →
95%) when a well-tuned schema description means they never do. Full numbers,
method, and the failure analysis are in [eval/RESULTS.md](eval/RESULTS.md).

See [docs/SETUP.md](docs/SETUP.md) for the git/repo setup steps, and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) to put it online for free (single Render service + Neon Postgres).

## Roadmap

Near-term priorities are in [docs/ROADMAP.md](docs/ROADMAP.md). Longer term:

- **Phase 2**: Model Context Protocol (MCP) — talk to the database through a Postgres MCP server over stdio instead of a direct driver.
- **Phase 3**: Human-in-the-Loop (HITL) approval for destructive queries, replacing the current hard block.
- **Phase 4**: ~~Postgres checkpointer for cross-session memory~~ — ✅ built, see [Conversation memory](#conversation-memory). Multi-tenant isolation (one namespace per user, not just per thread) is still open.

## Positioning

Part of an **"Agentic Self-Correcting Systems"** portfolio theme alongside [Adaptive CRAG](../adaptive-crag) and [Code Guardian](../code-guardian) — same underlying idea (LLM + self-verification + autonomous correction) applied to three different failure domains: SQL *execution errors*, retrieval *relevance*, and code *defects*.
