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
    question: str                  # Original natural language question
    sql_query: str                 # Most recently generated SQL statement
    query_result: str              # Raw database output (stringified rows)
    error: str                     # Exception message; empty string means success
    retry_count: int               # Current retry iteration (ceiling: MAX_RETRIES = 3)
    final_answer: str              # Validated natural language response
    logs: List[str]                # Step-by-step trace logs for UI visibility
    history: List[ConversationTurn]  # Prior turns, carried by the checkpointer
```

`logs` is threaded through every node, so the API can return the complete decision trace — this is the explainability story, and the most demo-worthy part of the response payload.

`history` is what makes a follow-up question mean anything; see §6c.

---

## 4. Safety Model **[Implemented, with Planned extension]**

Two layers today:

1. **Pre-execution keyword guard** — `execute_sql` rejects any query containing `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, or `TRUNCATE` before it touches the database, and sets `retry_count` to the maximum so the graph exits rather than looping on an unfixable request.
2. **Synthesis system prompt** — forbids revealing raw table/column names, bars listing multiple people's salaries unless an explicit comparison was requested, and states that the system is strictly read-only so the answer can never claim a write occurred.

### The false-confirmation bug (found in manual testing, fixed)

Asked *"Delete all employees from HR"*, the agent behaved correctly at every layer that touches data — the system prompt kept generation to `SELECT`, so the keyword guard never even had to fire, and nothing was written. Then the synthesizer read the question, saw two rows come back, and answered:

> "The employees Anjali Nair and Vikram Singh have been removed from the HR department."

Nothing had been removed. The guard held; the *narration* lied.

This is worth stating precisely because it is a failure mode the obvious threat model misses. Every safety layer in the system was aimed at preventing an unauthorised write, and all of them worked. But a user who is told a deletion succeeded is harmed whether or not the deletion happened — they may stop looking for records that still exist, or report the change as done. **A false confirmation is its own class of harm, independent of the action it describes.**

The fix is in the synthesis system prompt: the model is told the system is strictly read-only and must never state or imply that data was added, changed or removed; when a question asks for a modification it should say plainly that it can only read, then describe what the query returned. The agent now answers *"I can only read data and cannot perform deletions"* followed by the HR roster.

The general lesson, and the reason this belongs in the spec rather than a commit message: guarding the *action* is not the same as guarding the *report of the action*, and only end-to-end testing through the real UI surfaced the gap.

**Known limitation, stated honestly:** the keyword check is substring matching, so it is conservative — a legitimate query containing the word "updated" in a string literal is treated as destructive. That is deliberate: a false positive costs one unnecessary approval prompt, a false negative changes data nobody agreed to change. It is a demo-appropriate net, not a production authorization model. The correct production answer is a database-level read-only role, which costs nothing and cannot be prompt-injected around.

**[Planned]** remaining here is the Guardrails AI validator node. The Phase 3 HITL approval is now implemented — see §4a, which replaces the hard block with an approval pause on the `thread_id` path.

---

## 4a. Human-in-the-Loop Approval **[Implemented]**

A destructive query no longer dies at a hard block. It pauses, shows the human the exact statement, and waits.

```
generate_sql ──[needs_approval]──> await_approval ──[after_approval]──> execute_sql
     │                              (graph stops here)         │
     └──[not destructive]──────────────────────────────────────┘
                                             └──[rejected]──> synthesize
```

### Why a dedicated node instead of interrupting `execute_sql`

The pinned LangGraph version has no dynamic `interrupt()` — only static `interrupt_before=[...]`, which fires every time the named node is about to run. Putting that on `execute_sql` would pause *every* query, including plain `SELECT`s. A separate `await_approval` node makes the pause **conditional**: routing decides whether this turn passes through the gate at all.

`await_approval` deliberately asks nothing. The graph stops *before* it, so by the time the node actually runs the decision is already in state — the node's job is to record it, so the trace shows both what the run paused for and what it resumed on. A resume that arrives with no decision is recorded as a rejection: silently proceeding would defeat the entire gate.

### HITL requires the checkpointer — that ordering is not a coincidence

Pausing and later resuming means the graph's state has to live somewhere between two HTTP requests. Without a checkpointer there is nothing to resume *from*, so `interrupt_before` is meaningless. The stateless path (no `thread_id`) therefore keeps the original hard block, and that is the right behaviour rather than a gap: **offering an approval prompt that cannot be honoured is worse than refusing outright.** Phase 4 landing before Phase 3 is what made Phase 3 possible.

### The generation prompt had to change, or the gate would be dead code

The system prompt said *"only ever write SELECT queries"*. That constraint existed **because there was no gate** — any write the model produced would have gone straight to the database. Leaving it in place after building the gate would mean destructive SQL is never generated, so the gate never fires, and the whole phase is unreachable code that demos as working because nothing ever reaches it.

So the constraint is now conditional on `hitl_enabled`: on the gated path the model may write an `INSERT`/`UPDATE`/`DELETE` when the user explicitly asks for one, because a human reviews every such statement before it runs. On the stateless path the original hard line stands.

### `ALLOW_WRITES` — approved is not the same as committed

| `ALLOW_WRITES` | Approved statement |
|---|---|
| `false` (default) | Executes, then **rolls back**. Postgres plans it, enforces every constraint, and reports the rows it would have touched |
| `true` | Executes and commits |

This is what lets the approval flow be demonstrated on a public deployment without handing any visitor the ability to empty the table. It is explicitly **not** approval theatre: the response says plainly that the statement was rolled back and how many rows it would have affected. Running in a safe mode and saying so is a different thing from claiming an action happened.

The synthesis system prompt is conditional on the same flag. Hardcoding *"this system is strictly read-only"* was correct before writes existed; leaving it after `ALLOW_WRITES=true` would make the model deny a write that genuinely committed. **The guard has to work in both directions — no false confirmation, and no false reassurance.** That is the same lesson as the false-confirmation bug in §4, applied to its mirror image.

### API

| Endpoint | Behaviour |
|---|---|
| `POST /api/query` | Returns `awaiting_approval: true` with the pending statement in `sql_query` and an empty `final_answer` |
| `POST /api/approve` | `{thread_id, approved}` — resumes the paused graph |

`awaiting_approval` is a distinct flag rather than an inferred one: an empty `final_answer` on its own reads as "nothing found", when in fact the system is waiting on the user. Approving a thread that is not paused returns **409**, not 200 — a double-click or a stale tab is neither a server fault nor a malformed request, and answering 200 would tell the user their decision was applied when nothing happened.

Resume calls `update_state` then `invoke(None)`. Passing the original input again would restart the turn and spend another generation call; `None` means "continue from where you stopped".

`/api/approve` is rate limited alongside `/api/query` — resuming runs a synthesis call, so it costs the same quota as a new question.

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
| `/health` | GET | — | `{"status": "ok"}` — platform healthcheck and uptime pingers |
| `/api/health` | GET | — | Same, for the SPA |
| `/api/query` | POST | `{"question": str, "thread_id": str \| null}` | `{question, sql_query, final_answer, logs, retry_count, thread_id, memory_active}` |

Everything the SPA calls lives under `/api` so it cannot collide with a static file path once the built frontend is mounted at `/` (see §8). The bare `/health` is kept at the root because platform health checks and uptime pingers expect it there; both health routes are exempt from rate limiting so a keep-alive ping can never throttle the service it is keeping alive.

`thread_id` is optional. Omit it and the API behaves exactly as it did before conversation memory existed — which is what the eval harness and tests rely on. `memory_active` reports whether memory *actually* engaged, which is not the same as having sent a `thread_id`: checkpointer setup can fail (database unreachable, permissions) and the agent then runs stateless on purpose. Surfacing that distinction matters because a silently-stateless agent looks to the user like an agent that forgot.

`init_db()` runs on FastAPI startup, so table creation and seeding need no manual step.

**Rate limiting [Implemented]** — `/api/query` is limited per IP (default 5 requests per 60s, env-tunable). This is not polish: the public demo runs on a free Gemini tier of roughly 15 requests per minute shared across every visitor, so without a limit one enthusiastic visitor exhausts the quota and everyone after them sees errors. The limiter is in-memory by design — correct for a single container, wrong for multiple replicas, where a shared store would be needed.

**CORS** — `ALLOWED_ORIGINS` defaults to `*`. The single-service deployment serves the SPA from this same app, so there is no cross-origin caller to allow and the rate limiter is the real control. A split deployment should name the frontend origin explicitly.

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

## 6b. Evaluation Harness **[Implemented]**

`eval/` holds 20 natural-language questions with gold SQL, and a harness that measures whether the self-healing loop earns its complexity.

**Metric — execution accuracy.** The harness executes both the gold query and the agent's query and compares result sets. It deliberately avoids the two easier options: comparing SQL strings (many different queries are equally correct, so that measures stylistic agreement) and LLM-as-judge (that moves the reliability problem into a component nobody is measuring).

Two numbers are reported:

| Metric | Rule | Measures |
|---|---|---|
| **Accuracy** (headline) | Same row count; every gold row's values appear as a subset of a distinct agent row | Did it find the right answer? |
| **Strict** | Exact set-of-rows equality | Did it also project exactly the expected columns? |

The relaxed headline exists because the questions do not specify a projection. *"Who is the highest paid employee?"* is answered correctly by `SELECT name` and equally correctly by `SELECT name, salary, role` — scoring the latter wrong measures prompt compliance, not SQL correctness. Column names are ignored in both (aliasing is not an error), and numbers compare at 2dp so a `Decimal` average matches a rounded float.

**The experiment.** The same 20 questions run at `MAX_RETRIES=0` (loop disabled — one shot, a failure stays a failure) and `MAX_RETRIES=3` (the real system). That isolates the contribution of the *architecture* from the contribution of the *model*, which a single accuracy number cannot do. `graph.py` reads `MAX_RETRIES` as a module global at call time, so the harness patches the attribute between runs instead of restarting the process.

**Rate limiting is a first-class concern, not an afterthought.** Gemini free-tier quotas are small — some models allow only **20 requests per day** — and one self-healing run can issue up to 5 LLM calls. A 429 mid-eval is expected, so the harness backs off exponentially and retries the whole question; a question that still fails after 5 attempts is recorded as an error rather than silently dropped. Quotas are per-model, so eval runs use a `-lite` model via `GEMINI_MODEL` while the demo uses the standard one.

Every gold query is validated against the live schema before use — a broken gold query would silently corrupt the metric rather than fail loudly.

See [../eval/README.md](../eval/README.md) for usage.

---

## 6c. Conversation Memory — Postgres Checkpointer **[Implemented]**

Without memory, every `/api/query` starts from an empty state, so a follow-up like *"how many of those are in Bangalore?"* is a meaningless sentence — the agent has no referent for "those". LangGraph's checkpointer makes graph state survive between invocations, keyed by `thread_id`.

### Memory is two things, and both are required

A checkpointer alone does **not** make follow-ups work. It makes state *durable*; it does not put that state in front of the model. So `AgentState` carries a `history` list, and `_format_history()` renders the recent turns into the generation prompt. Durable state **plus** that state reaching the prompt — either half alone does nothing.

The rendered history includes **each turn's SQL, not just its answer**. If the previous question was "which department has the highest average salary?", the SQL contains `GROUP BY d.name ORDER BY AVG(e.salary) DESC LIMIT 1` — which tells the model precisely what "those" refers to. An English answer conveys that far less exactly.

Only the last `HISTORY_TURNS_IN_PROMPT` turns (default 3) go in. Sending everything costs tokens, but the sharper problem is attention: a twenty-turn-old exchange usually has nothing to do with the current question, yet the model treats it as context and lifts entities out of it.

### Which state is per-turn and which is per-conversation

This distinction did not exist before the checkpointer, because every invocation started clean. Now state survives, and LangGraph **merges** the input dict over the checkpointed state — so any key not present in the input carries forward.

That makes `run_agent` explicitly reset `question`, `sql_query`, `query_result`, `error`, `retry_count`, `final_answer` and `logs` on every new question, and deliberately omit `history`. Getting this wrong is not a subtle degradation: a previous turn's two retries would push the next question straight to "give up", and the trace shown in the UI would contain the *previous* question's lines. One decision separates a memory feature from a memory bug.

`history` deliberately has **no** additive reducer (`Annotated[..., operator.add]`). Nodes return `{**state, ...}`, so each one already returns the whole history; an additive reducer would re-append it at every node and grow the list exponentially. With overwrite semantics, exactly one place appends exactly one turn — `synthesize_and_validate`, via `_append_turn`. Failed turns are recorded too: dropping them would let the next follow-up silently reference a turn the model cannot see.

### Why Postgres, and why it is allowed to fail

`MemorySaver` would work until the process restarts. On Render's free tier the container sleeps after 15 minutes; a user returning to ask a follow-up would find the conversation gone. Postgres is already in this stack, so durable checkpointing costs no new service.

Setup is wrapped in a `try`/`except` and returns `None` on failure — the agent then runs stateless. That fallback is intentional: a chat app losing its memory feature is one kind of outage, the app failing to start is a worse one. It is deliberately **not** silent, though; the API returns `memory_active` so the UI can tell the user whether follow-ups will work, rather than leaving them to conclude the agent has forgotten.

The checkpointer is a process-wide singleton, cached with the failure result. It owns a connection pool, and opening a new pool per request is the most direct route to a connection leak. Compiled graphs are cached for the same reason (`_graphs`, keyed stateless/memory) — rebuilding per request was merely wasteful before and is incorrect now.

`autocommit=True` on the pool is load-bearing: `PostgresSaver` assumes each checkpoint write commits itself, and without it writes sit in an open transaction that the next request cannot see.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DISABLE_CHECKPOINTER` | unset | Force stateless mode even with a database available |
| `CHECKPOINTER_POOL_SIZE` | `5` | Connection pool ceiling |
| `HISTORY_TURNS_IN_PROMPT` | `3` | Prior turns rendered into the prompt |

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
| ~~Phase 3~~ | ~~Human-in-the-Loop (HITL)~~ | ✅ **Done** — see §4a. Static `interrupt_before` on a dedicated approval node, `/api/approve` to resume, and `ALLOW_WRITES` deciding whether an approved statement commits or runs-and-rolls-back. Still outstanding: the approval is unauthenticated, exactly like `thread_id` — anyone holding the thread id can approve a write on it. Real use needs auth on the approve endpoint, not just on the query |
| ~~Phase 4~~ | ~~Postgres checkpointer~~ | ✅ **Done** — see §6c. Cross-session conversation memory via LangGraph's persistence layer. Multi-tenant isolation is the part still outstanding: `thread_id` is client-supplied and unauthenticated, so anyone who guesses another thread's id reads that conversation. Fine for a single-user demo, not for multi-tenant use — that needs auth and a per-user namespace on the thread key |
