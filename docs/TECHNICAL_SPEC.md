# Self-Healing Data Query Agent: Technical Specification

Comprehensive technical specification and architecture for the Self-Healing Data Query Agent. Built with LangGraph, LangChain, Google Gemini, FastAPI, PostgreSQL, and React, this system translates natural language questions into SQL, autonomously detects execution errors, runs a self-healing reflection loop, and validates its output before returning it.

> **Reading this doc:** sections marked **[Implemented]** describe code that exists in `backend/app/`. Sections marked **[Planned]** are roadmap items and are not built yet. Nothing here is described as done unless it is done.

---

## 1. Executive Summary & Core Objectives

Traditional Text-to-SQL systems fail when they hit complex joins, dialect differences, or ambiguous phrasing. Without a feedback loop, one database error becomes a broken user experience — the classic single-shot pipeline has no way to learn from the failure it just caused.

The Self-Healing Data Query Agent solves this with cyclical graph-based execution:

- **Cyclic state graph** — LangGraph conditional edges implement a stateful retry loop that re-enters the generation node carrying the failure context. **[Implemented]**
- **Error-informed regeneration** — the retry prompt contains the previous SQL *and* the exact database exception, so the model corrects a specific fault rather than resampling blindly. **[Implemented]**
- **Read-only enforcement** — destructive SQL is blocked before it reaches the database. **[Implemented]**
- **Output safety** — synthesis runs under a system prompt that forbids schema leakage and bulk salary disclosure. A dedicated Guardrails AI validator node is **[Planned]**.
- **Full-stack decoupling** — the state machine is exposed via a modular FastAPI REST interface, with a React frontend and Docker orchestration.

---

## 2. System Architecture & Component Breakdown

Three layers: UI client, orchestration/backend, and data persistence.

| Component | Technology | Primary Role | Status |
|---|---|---|---|
| Agent Workflow | LangGraph (Python) | State machine, node transitions, conditional self-correction branching | Implemented |
| LLM Inference | LangChain + Google Gemini 2.0 Flash | SQL generation, error reflection, natural language synthesis | Implemented |
| Data Store | PostgreSQL 16 (SQLAlchemy Core + psycopg2) | Target relational database for generated queries | Implemented |
| API Backend | FastAPI + Uvicorn | REST endpoints serving agent execution, trace logs, responses | Implemented |
| Output Validation | Guardrails AI | Dedicated validator node for toxicity / groundedness / schema integrity | Planned |
| Frontend UI | React + Vite | Chat interface exposing agent trace logs and generated SQL | Planned |
| Containerization | Docker & Docker Compose | Three-service stack with Nginx serving the frontend | Implemented |

### Why Gemini 2.0 Flash

Chosen over Groq/Llama and GPT for three reasons: a genuinely usable free tier (this is a portfolio project, not a funded product), low latency on short structured outputs — which matters because a self-healing run can issue up to 4 generation calls plus a synthesis call — and strong instruction-following on "return only SQL, no prose", which keeps the `_extract_sql` parser simple. `temperature=0` throughout: SQL generation wants determinism, not creativity. The provider sits behind LangChain's chat interface, so swapping it is a one-line change in `_llm()`.

### Why PostgreSQL, not SQLite

An earlier draft of this project targeted SQLite. It was switched to Postgres because SQLite's permissive type affinity and forgiving parser mean many genuinely wrong queries still *succeed* — which starves the self-healing loop of the very errors it exists to fix. Postgres has strict typing, real constraint enforcement, and precise error messages (`column "salery" does not exist`), which is exactly the high-quality feedback signal the retry prompt depends on. It is also what the target production environment would actually be.

---

## 3. LangGraph State Machine & Self-Healing Logic **[Implemented]**

```
+-------------------+
|    User Prompt    |
+-------------------+
          |
          v
+-------------------+
|   generate_sql    | <---------------------+
+-------------------+                       |
          |                                 | "retry"
          v                                 | (error AND retry_count < 3)
+-------------------+                       |
|    execute_sql    | -- [Conditional Edge] +
+-------------------+       should_retry
          |    |
          |    | "give_up" (error AND retries exhausted)
          |    v
          | +------------------------+
          +>| synthesize_and_validate|
 "success"  +------------------------+
                       |
                       v
                     [END]
```

`should_retry` is what makes this a **cyclic** graph rather than a linear chain — LangGraph decides the next node at runtime from the state, so `generate_sql` can be re-entered. That is the architectural difference between this and a `for` loop wrapped around a chain: the retry is a first-class edge in the graph, the full attempt history lives in the state object, and the trace is inspectable node by node.

### Node contracts

| Node | Reads from state | Writes to state | Notes |
|---|---|---|---|
| `generate_sql` | `question`, `error`, `sql_query`, `retry_count` | `sql_query`, `logs` | Branches internally: fresh prompt if `error` is empty, error-repair prompt otherwise |
| `execute_sql` | `sql_query` | `query_result`, `error`, `retry_count`, `logs` | Destructive-keyword guard runs *before* the database call |
| `synthesize_and_validate` | `question`, `query_result`, `error` | `final_answer`, `logs` | On `give_up`, returns a graceful message instead of a raw traceback |

### The retry prompt (the actual USP)

On failure the agent does **not** re-run the original prompt. It sends the schema, the question, the SQL that failed, and the verbatim database error, with the instruction to fix it. This is reflection, not resampling: the model is given a concrete, specific fault to correct.

### Retry budget: why 3

Empirically, genuine syntax/schema mistakes are corrected on the first or second retry once the model can see the error. Failures that survive three attempts are almost always *semantic* — an unanswerable question, or a column that does not exist in any form — and more retries just burn tokens and latency to arrive at the same failure. Three is a deliberate cost/latency ceiling, defined as `MAX_RETRIES` in one place so it is trivially tunable (and the planned eval harness sweeps it).

### State Definition **[Implemented]**

```python
class AgentState(TypedDict):
    question: str       # Original natural language question
    sql_query: str      # Most recently generated SQL statement
    query_result: str   # Raw database output (stringified rows)
    error: str          # Exception message; empty string means success
    retry_count: int    # Current retry iteration (ceiling: MAX_RETRIES = 3)
    final_answer: str   # Validated natural language response
    logs: List[str]     # Step-by-step trace logs for UI visibility
```

`logs` is threaded through every node, so the API can return the complete decision trace — this is the explainability story, and the most demo-worthy part of the response payload.

---

## 4. Safety Model **[Implemented, with Planned extension]**

Two layers today:

1. **Pre-execution keyword guard** — `execute_sql` rejects any query containing `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, or `TRUNCATE` before it touches the database, and sets `retry_count` to the maximum so the graph exits rather than looping on an unfixable request.
2. **Synthesis system prompt** — forbids revealing raw table/column names and bars listing multiple people's salaries unless an explicit comparison was requested.

**Known limitation, stated honestly:** the keyword guard is substring matching, so it is conservative — a legitimate query containing the word "updated" in a string literal would be blocked. It is a demo-appropriate safety net, not a production authorization model. The correct production answer is a database-level read-only role, which costs nothing and cannot be prompt-injected around. **[Planned]** work is the Guardrails AI validator node and Phase 3 HITL approval, which replaces the hard block with an approval pause.

---

## 5. Database Schema & Sample Dataset **[Implemented]**

PostgreSQL, representing an enterprise employee directory. Two related tables, seeded with 4 departments and 10 employees.

**`departments`**

| Column | Data Type | Constraints | Description |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | Unique identifier |
| `name` | TEXT | NOT NULL UNIQUE | Engineering, Marketing, HR, Sales |
| `budget` | INTEGER | NOT NULL CHECK (budget > 0) | Annual department budget |
| `location` | TEXT | NOT NULL | City — Bangalore, Mumbai, Delhi, Pune |

**`employees`**

| Column | Data Type | Constraints | Description |
|---|---|---|---|
| `id` | SERIAL | PRIMARY KEY | Unique identifier for the employee record |
| `name` | TEXT | NOT NULL | Full name of the employee |
| `department_id` | INTEGER | NOT NULL REFERENCES `departments(id)` | Foreign key to the owning department |
| `salary` | INTEGER | NOT NULL CHECK (salary > 0) | Annual base compensation |
| `role` | TEXT | NOT NULL | Job title / functional role |

### Why two tables

The single flat `employees` table this project started with could not exercise the hard part of Text-to-SQL. Every question reduced to a `WHERE` filter on one table, which a model gets right almost every time — so the self-healing loop had nothing realistic to heal. With a foreign key, the model must *infer the join* from the schema description: `"employees in Bangalore"` requires recognising that location lives on `departments`, that `employees` has no department name at all, and that `department_id` is the bridge. Getting a join wrong is the single most common real Text-to-SQL failure, and it produces exactly the kind of precise Postgres error (`column e.department does not exist`) that the retry prompt is built to consume.

The schema is handed to the LLM as a plain-text description from `get_schema_description()` rather than by introspecting the live database. Deliberate: the description carries *semantic* hints that raw DDL does not — example values for `name` and `location`, an explicit `employees.department_id -> departments.id` relationship line, and a direct statement that `employees` has **no** department-name column so a join is mandatory. Introspection would give the model the columns but not that guidance, and prompt token cost stays fixed and predictable this way.

### Schema migration

`init_db()` detects the legacy single-table shape (an `employees.department` TEXT column, via `information_schema`) and rebuilds both tables when it finds it. Data here is seed data only, so a drop-and-rebuild is safe and keeps `docker compose up` working on an existing volume without a manual step. This is demo-appropriate, not a production migration strategy — production would use Alembic. Seeding is idempotent: both tables are only populated when their row count is zero.

---

## 6. API Surface **[Implemented]**

| Endpoint | Method | Body | Response |
|---|---|---|---|
| `/health` | GET | — | `{"status": "ok"}` — Docker healthcheck |
| `/query` | POST | `{"question": str}` | `{question, sql_query, final_answer, logs, retry_count}` |

`init_db()` runs on FastAPI startup, so table creation and seeding need no manual step. CORS is currently `allow_origins=["*"]` for local development — a known item to tighten to the deployed frontend origin before deployment.

---

## 6a. Observability — LangSmith Tracing **[Implemented]**

The `logs` array gives the *user* a readable trace. It does not give the *developer* the raw prompts, token counts, or per-node latency needed to actually debug a bad run — so LangSmith is wired in alongside it.

Enabled purely by environment variable; there is **no tracing code in the application**:

```bash
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=<key from smith.langchain.com>
LANGCHAIN_PROJECT=self-healing-sql-agent
```

LangChain's callback system picks these up at import time and instruments every `ChatGoogleGenerativeAI` call automatically. Unset or `false` (the default in `.env.example` and `docker-compose.yml`) means zero overhead and zero behaviour change — nothing in the graph depends on it.

**What it buys on this particular project.** A self-healing run is inherently multi-step: up to four generation calls plus a synthesis call, with the prompt *changing between attempts*. When a run retries three times and still fails, the question a developer actually needs answered is "what exactly did the model see on attempt 2, and why didn't the error message fix it?" The `logs` array can't answer that — it records the SQL and the error, not the full prompt that produced them. LangSmith shows the retry chain as a nested trace: each `generate_sql` invocation, its exact rendered prompt including the injected error, the raw response before `_extract_sql` touched it, latency, and token cost per attempt.

That makes three things debuggable that were previously guesswork:

- **Prompt regressions** — if a schema-description edit quietly worsens generation, the diff is visible in the traced prompt.
- **Retry effectiveness** — whether attempt N+1 actually incorporated the error, or just re-emitted the same query.
- **Cost/latency attribution** — which node dominates a slow request, and what a retry genuinely costs in tokens.

**Design note:** two observability layers is deliberate, not redundant. `logs` is a *product* feature — it ships in the API response and drives the UI's explainability story. LangSmith is a *developer* tool — it stays server-side, carries raw prompts that should never reach a client, and is opt-in so a fork of this repo runs without a LangSmith account.

**[Planned]** Once the evaluation harness exists, its runs will be tagged into a LangSmith project so accuracy comparisons (`MAX_RETRIES=0` vs `3`) come with per-question traces instead of just an aggregate number.

---

## 7. End-to-End Execution Flow

1. **Ingestion** — the user submits a question (e.g. "Who earns more than 80000 in Engineering?").
2. **SQL construction** — `generate_sql` injects the schema description and question into a `temperature=0` Gemini call and extracts the SQL from the response, stripping any markdown fence.
3. **Guard & execute** — the destructive-keyword check runs, then `run_sql` executes against Postgres.
   - Success → rows are stringified into `query_result`, `error` is cleared.
   - Failure → the exception message is captured into `error` and `retry_count` increments.
4. **Conditional routing** — `should_retry` returns `retry`, `give_up`, or `success`.
5. **Synthesis** — rows become a short natural-language answer under the safety system prompt, or a graceful failure message if the budget was exhausted.
6. **Trace delivery** — the API returns the answer, the executed SQL, the retry count, and the full log array for client-side visualization.

---

## 8. Docker Containerization & Deployment Model **[Implemented]**

Three-service Docker Compose stack:

- **`db`** — `postgres:16` with a named `pgdata` volume and a `pg_isready` healthcheck; the backend waits on `service_healthy` so startup ordering is guaranteed rather than raced.
- **`backend`** — `python:3.11-slim`, requirements installed before the app code is copied so Docker layer caching survives code edits, running Uvicorn on port 8000.
- **`frontend`** — multi-stage Node build served by Nginx with `/api/` reverse-proxy routing. **[Planned — only a Dockerfile scaffold exists today.]**

Single command: `docker compose up --build`, with secrets injected from `.env` (never committed; `.env.example` is the template).

---

## 9. Future Extensions & Scaling Roadmap

Near-term, interview-focused priorities are in [ROADMAP.md](ROADMAP.md) — multi-table schema, evaluation harness, frontend, deployment. Beyond those:

| Phase | Enhancement | Technical Impact |
|---|---|---|
| Phase 2 | Model Context Protocol (MCP) | Replace the direct SQLAlchemy driver with a standard Postgres MCP server over stdio, so the data access layer becomes a swappable tool rather than hard-wired code |
| Phase 3 | Human-in-the-Loop (HITL) | LangGraph interrupt before executing destructive queries, replacing today's hard block with an approval pause |
| Phase 4 | Postgres checkpointer | Cross-session conversation memory and multi-tenant isolation via LangGraph's persistence layer |
