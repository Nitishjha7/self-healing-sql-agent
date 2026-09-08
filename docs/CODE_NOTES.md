# Code Notes — What Exists and Why

This file tracks the **job and the reason** for every file and dependency, so that later (or in an interview) it is clear why each thing was chosen. It gets updated as the code grows.

---

## backend/requirements.txt

| Package | What it does | Why it was chosen |
|---|---|---|
| `fastapi` | REST API framework — for defining endpoints (like `/query`, which triggers the agent) | Fast, async-native, gives automatic Swagger docs (at `/docs`); FastAPI is the industry standard for Python backends |
| `uvicorn[standard]` | The ASGI server that actually runs the FastAPI app | FastAPI is not a server itself; it needs one to run — Uvicorn is the most common choice |
| `langgraph` | Graph-based agent orchestration library | This is what builds the `AgentState` state machine — nodes (`generate_sql`, `execute_sql`, `synthesize`) and conditional edges (the retry loop) |
| `langchain` | Framework for interacting with the LLM (prompts, chains, message formatting) | Used for the LLM calls inside the LangGraph nodes |
| `langchain-google-genai` | LangChain's Gemini-specific connector | Gemini is the model in use (free tier). The model name is env-configurable (`GEMINI_MODEL`) because Google keeps deprecating model names — both `gemini-2.0-flash` and `gemini-2.5-flash` started returning 404 during this project — this package is what plugs Gemini into LangChain |
| ~~`guardrails-ai`~~ | Output validation library | **⚠️ Removed from requirements.** Two reasons: (1) it was never wired up — validation was only prompt-level at the time (in the `synthesize_and_validate` system prompt); (2) `0.5.10` requires `langchain-core<0.3` while langgraph, langchain and langchain-google-genai all require `>=0.3` — **this made `pip install` fail and the Docker image would not build at all.** When the validator node was actually built, a deterministic implementation replaced it (see `validators.py` below). Do not call this "implemented" in an interview |
| `sqlalchemy` | ORM/toolkit for talking to a SQL database from Python | For connecting to PostgreSQL and executing queries — more convenient than raw psycopg2 |
| `psycopg2-binary` | PostgreSQL driver (the actual low-level connector) | SQLAlchemy needs this driver to talk to PostgreSQL (SQLAlchemy is a wrapper, not a driver) |
| `python-dotenv` | Loads environment variables from a `.env` file | So secrets like `DATABASE_URL` and `GOOGLE_API_KEY` are read from `.env` rather than hardcoded |
| `pydantic` | Data validation / schema library | For defining FastAPI request/response models (e.g. `QueryRequest { question: str }`) — FastAPI is built on it internally |

---

---

## backend/app/db.py

**What it does:**
- Creates the SQLAlchemy `engine` that connects to PostgreSQL via the `DATABASE_URL` env var (falling back to localhost if the variable is missing).
- `init_db()` — creates the `departments`, `employees` and `projects` tables (if they do not exist) and seeds them when empty. It is called once when the container starts.
- `_needs_rebuild()` — detects the old single-table schema (it checks `information_schema` for an `employees.department` TEXT column). If found, the tables are dropped and rebuilt in the new shape. **Why:** the data is only seed data, so dropping is safe — and it means `docker compose up` works against an existing Docker volume with no manual step. This is demo-appropriate, not a production migration strategy (that would be Alembic).
- `get_schema_description()` — returns the schema as plain text. This goes into the LLM prompt so it knows the correct table and column names — the LLM has no "real" access to the database, we describe it in text.

**The two-table schema (why `department` TEXT became a FK):**
Originally there was a single flat `employees` table with `department` as a TEXT column. The problem was that every question became a single-table `WHERE` filter — which the model gets right on the first attempt almost every time. That meant **the self-healing loop had nothing to heal**, and the project's core selling point never fired in a demo.

Now `departments` (id, name, budget, location) is its own table and `employees.department_id` is a foreign key to it. That forces the model to **infer** the join: to answer "who works in Bangalore" it has to work out that location lives on `departments`, that `employees` has no department name at all, and that `department_id` is the bridge. Getting a join wrong is the most common real Text-to-SQL failure — and it produces exactly the precise Postgres error (`column e.department does not exist`) the retry prompt was built to consume.

**Three things are deliberately in the schema description** that raw DDL would not carry:
1. Example values (`'Engineering'`, `'Bangalore'`) — a semantic hint
2. An explicit relationship line: `employees.department_id -> departments.id`
3. A direct warning: `employees` has no department name column, so the join is **mandatory**

Live introspection would only give the columns, not this guidance — and this way the prompt token cost stays fixed and predictable.

- `run_sql(query)` — executes any SQL string and returns the result as a list of dicts (so it converts easily to JSON for the API response). If the query is wrong (syntax or schema error), SQLAlchemy raises an exception — that exception is caught in the LangGraph node and triggers the self-healing retry.

**Design choice:** the tables and columns are created with raw SQL (SQLAlchemy Core `text()`), not ORM models (declarative classes) — because the agent writes dynamic SQL itself, there is no need for fixed ORM models, only raw execution.

**Security note:** `run_sql` can technically run any SQL, which is why the guard sits in the `execute_sql` node — destructive keywords are caught **before** the DB call. Writes now go through `run_write`, which is a separate function where the caller decides whether to commit or roll back. **The correct production answer is still a database-level read-only role** — that cannot be bypassed by prompt injection, whereas keyword matching can.

---

---

## backend/app/graph.py, nodes.py, state.py, config.py

These four files are **the core of the project** — the self-healing LangGraph state machine. They were split out of a single 646-line `graph.py` because they change for different reasons: wiring, behaviour, shape, and settings.

**`AgentState`** (in `state.py`) — the TypedDict that carries the whole context from node to node: question, current SQL, result, error, retry count, final answer, logs. It is the schema from the spec.

**`_llm()`** (in `nodes.py`) — initialises Gemini through LangChain (the model comes from the `GEMINI_MODEL` env var, default `gemini-3.5-flash-lite`). `temperature=0` because SQL generation needs deterministic, precise output, not creative output.

**`_extract_sql()`** — the LLM sometimes returns SQL inside a ```sql ... ``` fenced block or with extra explanation. This helper pulls out just the clean SQL.

**The `generate_sql` node:**
- If `state["error"]` is empty → build a fresh prompt (schema + question).
- If there is an error (meaning the last query failed) → **the core of self-healing**: send both the previous SQL and the error message back to the LLM, so it can see exactly what went wrong and fix it. This is better than a plain "retry with the same prompt" because the LLM gets concrete feedback.

**The `execute_sql` node:**
- First a **safety check** (`is_destructive`): if the generated SQL contains a keyword like `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER` or `TRUNCATE`, then **on the stateless path** the query is blocked immediately (retry count is set to max so it exits the loop, because a policy rejection is not fixed by retrying). **On the `thread_id` path this is no longer a block but an approval gate** — see the "HITL approval gate" section below.
- Otherwise it calls `run_sql()` (from db.py). On success the result is saved into state; on an exception the error is saved and `retry_count` increments.

**`should_retry` — the conditional edge function:**
It decides which node the graph goes to next:
- There is an error and retries `< MAX_RETRIES (3)` → back to `generate_sql` (the retry loop)
- There is an error and retries are exhausted → `give_up` (synthesis produces an apology message)
- There is no error → `success` (normal synthesis)

This function is what makes the LangGraph a **cyclic graph** — not possible in a plain linear chain.

**The `synthesize_and_validate` node:**
- If every retry failed, it produces a clean "sorry" message (the raw exception is never exposed to the user).
- Otherwise the LLM writes a natural-language answer. The system prompt explicitly says not to reveal raw column/table names and not to show several people's salaries at once (basic schema-leakage and privacy guardrails). A deterministic output guard now enforces the leakage half of this — see `validators.py`.

**`build_graph()`** — wires the nodes together:
```
generate_sql → execute_sql → (conditional: retry → generate_sql | give_up/success → synthesize_and_validate) → END
```

**`run_agent(question)`** — the external entrypoint the FastAPI endpoint calls. It builds a fresh `AgentState`, invokes the whole graph, and returns the final state (containing `final_answer`, `sql_query` and `logs` — everything the UI needs to show).

**Interview-worthy point:** this "retry" is not a dumb `for` loop — it uses LangGraph's **conditional edge** feature, so the graph decides at runtime which node runs next, based on state. That is what makes it a real state machine rather than a sequential script.

---

---

## backend/app/main.py

The FastAPI entrypoint — the HTTP layer, no agent logic here. The endpoints themselves live in `app/api/`.

- **`lifespan` → `init_db()`**: the tables are created and seeded as soon as the container starts, with no separate manual step. (This replaces `@app.on_event("startup")`, which newer FastAPI deprecates.)
- **`GET /health`**: a simple ping endpoint for the Docker healthcheck and uptime checks.
- **`POST /api/query`**: what the frontend calls. The body carries `{"question": "..."}` and the response carries `sql_query`, `final_answer`, `logs` (the full trace) and `retry_count` — all of which the UI shows, for transparency.
- **CORS**: `ALLOWED_ORIGINS` is env-configurable, defaulting to `*` for local development so React (on a different port/container) can call the backend without CORS errors. In production it should be restricted to the specific frontend domain.
- **Pydantic models (`QueryRequest`, `QueryResponse`)**: they enforce the request/response shape — FastAPI derives validation and the `/docs` (Swagger UI) page from them automatically.

---

## backend/Dockerfile

A standard multi-stage Python container build:
1. `python:3.11-slim` base (a light image — not full Python, only what is needed)
2. Copy `requirements.txt` first and install (for Docker layer caching — if the code changes but the requirements do not, the install step does not run again)
3. Then copy the `app/` code
4. Run the app with `uvicorn` on port 8000

## LangSmith tracing (env vars only — no code)

**What it is:** setting `LANGCHAIN_TRACING_V2=true` plus `LANGCHAIN_API_KEY` and `LANGCHAIN_PROJECT` makes LangChain send every LLM call to LangSmith by itself — **there is not one line of tracing code in the application.**

**How it works:** LangChain's callback system reads those env vars at import time and instruments every `ChatGoogleGenerativeAI` call automatically. Both `.env.example` and `docker-compose.yml` default it to `false`, so the repo runs normally without a LangSmith account — zero overhead, zero behaviour change.

**Why it was added (and why the `logs` array was not enough):**
`logs` is for the **user** — a readable trace that goes out in the API response and is shown in the UI. It does not contain the raw prompt (and should not — that must not reach the client).

LangSmith is for the **developer**. A self-healing run is inherently multi-step — up to 4 generation calls plus synthesis — and **the prompt changes on every attempt**. When something still fails after three retries, the real question is: *"what exactly did the model see on attempt 2, and why did the error message not get it to fix things?"* — `logs` can never answer that, because it records the SQL and the error, not the full prompt that produced them.

In LangSmith the retry chain appears as a nested trace: every `generate_sql` invocation, its exact rendered prompt (with the injected error), the raw response before `_extract_sql`, latency, and per-attempt token cost.

**Three things this makes debuggable:**
- **Prompt regression** — did editing the schema description degrade generation? The diff is visible in the traced prompt
- **Retry effectiveness** — did attempt N+1 actually incorporate the error, or did it write the same query again?
- **Cost/latency attribution** — which node is heavy in a slow request, and how expensive is one retry in tokens

**Design choice:** having two observability layers is deliberate, not redundant — one is a product feature (`logs`, which reaches the client), the other a developer tool (LangSmith, which stays server-side and carries raw prompts). That is why LangSmith is opt-in.

**Interview value:** "how would you debug an agent that takes a wrong step?" is the most common production question about agentic AI. The answer is no longer "there is a logs array", it is "the whole retry chain shows up in LangSmith as a nested trace, at prompt level".

---

## .env.example

The real secrets (`.env`) are in `.gitignore` so they are never committed. This `.env.example` file is only a **template** — it lists which env vars are needed (`DATABASE_URL`, `GOOGLE_API_KEY`, etc.) without leaking real values. Copy it to `.env` and put your own Gemini API key in.

## docker-compose.yml fix

`GROQ_API_KEY` was left behind from when Groq was going to be the provider — after switching to Gemini it became `GOOGLE_API_KEY` so the backend container gets the right env var.

---

## Every new file gets its explanation added below.

---

## frontend/ — React + Vite chat UI

**What it is:** a single-page chat interface that calls `POST /api/query` and renders the response readably.

| File | Job |
|---|---|
| `src/App.jsx` | State and composition — chat state, fetch calls, view switching |
| `src/components/` | Sidebar, top bar, feature strip, icons, SQL block, charts |
| `src/chat/` | Chat view, one turn, result table, composer, trace panel |
| `src/views/` | Dashboard, generated dashboard, schema, history, eval, settings |
| `src/Shell.css` | Layout and component styling |
| `src/index.css` | CSS variables (light + dark), base typography |
| `vite.config.js` | React plugin + dev-server proxy (for `npm run dev`; in the container nginx handles it) |
| `nginx.conf` | SPA fallback + `/api/` reverse proxy to the backend |
| `Dockerfile` | Multi-stage — node build, then nginx serve |

**Design choices and their reasons:**

- **No UI library (no Tailwind, no MUI)** — the UI is small enough that plain CSS is sufficient. Adding a dependency means build complexity and bundle size for no benefit. This is defendable in an interview: "chosen to fit the scope, not out of habit."
- **The retry badge (`First try` / `Self-healed after N retries`)** — the single most important element in the UI. `retry_count` is the one number that *proves* self-healing; making it a badge means it is visible immediately in a demo.
- **A collapsible "Show SQL & steps"** — closed by default, because a normal user wants the answer. Opening it shows the executed SQL and the full `logs` array. This is the explainability part — not a black box.
- **Colour coding in the trace** — `Execution failed` / `Blocked` in red, `Retry N` in amber, `Execution succeeded` in green. Otherwise the logs read as an undifferentiated wall of text and the self-healing moment gets lost in it.
- **An nginx proxy rather than a direct backend call** — the frontend calls `/api/query` on its own origin, so CORS never arises in the browser and the backend does not need to be publicly exposed.
- **`proxy_read_timeout 180s`** — nginx defaults to 60s. A self-healing run can make up to 5 LLM calls; the default timeout would cut it off mid-retry and the user would get a 504 while the agent was working correctly.
- **`package.json` copied first in the Dockerfile** — layer caching, the same reason as in the backend.

**Ports:** both are overridable in `docker-compose.yml` (`BACKEND_PORT`, `FRONTEND_PORT`) — because 8000 and 80 are often already taken by other projects on the machine.

---

## The read-only narration guard (added later)

These lines were added later to the `synthesize_and_validate` system prompt:

> "This system is STRICTLY READ-ONLY... Never state or imply that data was added, changed, removed or otherwise modified."

**Why:** during UI testing, "Delete all employees from HR" was asked. Every data-touching layer behaved correctly — the system prompt kept generation to a SELECT, the keyword guard never even needed to fire, and nothing in the database changed. **Then the synthesizer answered: "The employees Anjali Nair and Vikram Singh have been removed from the HR department."**

Nothing had been removed. The guard protected the data, but the narration lied — and a user who is told a deletion happened is harmed all the same. **A false confirmation is its own class of harm.**

It is a useful reminder: the whole threat model had been focused on "unauthorised write", and all those layers were working. The gap was that the *action* was guarded but its *report* was not.

---

## backend/app/ratelimit.py — per-IP rate limiting

**What it does:** a per-IP sliding-window limit on `/query` (5 questions / 60 seconds by default), configurable through env vars.

**Why it matters (this is not polish):** on a public demo the Gemini free tier gives ~15 requests/minute for **the whole project** — shared across every visitor. One bot, or one curious recruiter asking 20 questions, exhausts the quota and **every** visitor after that gets an error. Without a rate limit the demo breaks itself.

**Design choices:**
- **An in-memory dict of deques, no Redis** — the right trade-off for a single-container demo. With multiple replicas each process would keep its own count, and that needs a shared store. **Say this limitation yourself in an interview** — knowing the trade-off is the actual point.
- **`/health` deliberately exempt** — pingers like UptimeRobot and the platform's own health checks must never be throttled. If `/health` were limited, the keep-alive ping itself would block the service.
- **The first entry of `X-Forwarded-For`** — Cloud Run, Cloudflare and nginx all terminate the connection themselves, so `request.client.host` is the proxy's IP. The header is spoofable in general, but these platforms overwrite it, and the cost of getting it wrong is only that the wrong visitor is throttled — this is not a security boundary.
- **A `MAX_TRACKED_IPS` ceiling** — without it the dict grows with every new IP. An unbounded dict fed by user-controlled keys is a memory leak.

**Verified:** 5 requests pass, the 6th returns 429 with `Retry-After`, and `/health` is never throttled.

---

## main.py — configurable CORS

The `ALLOWED_ORIGINS` env var (comma-separated), default `*`.

**Why:** locally the frontend is served through nginx on the same origin, so CORS is not needed at all. On a split deploy the frontend (Cloudflare Pages) and backend (Cloud Run) are on different origins — then CORS is needed, **but only for your own frontend**. Leaving it as `*` means any website can call your backend and burn your LLM quota.

`allow_methods` was also narrowed from `["*"]` to the methods actually used, and headers to just `Content-Type` — the API only uses those, and there is no reason to leave the rest open.

---

## frontend — VITE_API_BASE

In `App.jsx`: `const API_BASE = import.meta.env.VITE_API_BASE || ""`.

The default is empty — in the Docker setup nginx proxies `/api` on the same origin, so a relative URL is what is wanted. On a split deployment `VITE_API_BASE` is set at build time.

**Watch out:** this is a **build-time** variable, not a runtime one — Vite bakes it into the bundle. After changing the value on Cloudflare Pages you **must redeploy**, otherwise the old value keeps being used. This is a common gotcha.

**429 handling:** the frontend catches `res.status === 429` separately and shows the backend's `detail` message — because being throttled is a normal, explainable state, not a generic error.

---

## Dockerfile (root) — the single-service deployment image

**What it does:** a two-stage build. Stage 1 builds the React app with Node; stage 2 builds the Python image and copies those built files into `static/`. FastAPI serves both the API and the UI.

**Why it differs from `backend/Dockerfile`:** that one is for local `docker-compose`, where nginx serves the frontend separately. This root one is for deployment. Both are kept because the nginx setup in local dev demonstrates a production-like reverse proxy, while a single service is the simplest thing to deploy.

**Why `CMD` is in shell form:** Render (and most PaaS platforms) inject a `$PORT` env var that must be bound. In exec form (`["uvicorn", ...]`) `${PORT}` is not expanded — the literal string is passed through. So `sh -c` is used, with a `${PORT:-8000}` default so a local `docker run` works too.

---

## main.py — the `/api` prefix and the static mount

**Why the `/api` prefix:** the built frontend is mounted at `/`, and that mount swallows every path below it. If the API routes were at `/query` they would collide with the static mount. Keeping everything under `/api/*` lets both coexist.

**Why the mount is last:** FastAPI matches routes in registration order. Writing `app.mount("/")` first would let it swallow the API routes too. So it is mounted **after** the routers are included, with a comment in the file so nobody moves it up by accident.

**Why `/health` exists twice:** `/api/health` is consistent for the frontend, and `/health` at the root because platform health checks and uptime pingers expect it there. Both are exempt from the rate limiter.

**`if STATIC_DIR.is_dir()`** — in the compose setup `static/` does not exist (nginx serves it). Without this check the app would crash there. One codebase supports both deployment shapes.

**The trailing slash was removed from nginx's `proxy_pass`** — it used to be `http://backend:8000/`, which stripped the `/api` prefix. FastAPI now expects `/api` itself, so the path has to be preserved.

---

## render.yaml

A Render Blueprint — it keeps the service settings in version control (rather than clicking through the dashboard).

**The database is deliberately not defined here** — Render's free Postgres **expires after 30 days**. The portfolio link would die quietly with no warning. The Neon free tier does not expire.

**Secrets are `sync: false`** — meaning the value goes in the Render dashboard, not in the YAML. The Blueprint is committed; putting an API key in it would be the same mistake as putting one in `.env.example`.

## backend/app/checkpointer.py — conversation memory (added later)

**What:** a process-wide `PostgresSaver`, built lazily and fail-open.

**Why Postgres and not `MemorySaver`:** `MemorySaver` keeps state in the process. Render's free tier sleeps after 15 minutes — the user comes back, asks a follow-up, and the conversation is gone. Postgres is already in this stack, so durability needs no new service. **Verified:** the backend container was restarted mid-conversation, then "that department's budget?" was asked on the same thread — the history came back from Postgres and the reference resolved correctly.

**Why a pool and `autocommit=True`:** a `PostgresSaver` holds a connection pool, so it is built exactly once (a new pool per request is a connection leak). Without `autocommit`, checkpoint writes hang in an open transaction and the next request never sees them.

**Why fail-open:** if the DB is unreachable the app does not crash, memory switches off quietly — but the API returns `memory_active: false`. A feature being down is one thing; being down **silently** is another, because then the user thinks the agent forgot when memory was never on.

## graph.py — `history`, and per-turn vs per-conversation state

**The most important point:** the checkpointer alone does not make follow-ups work. It makes state durable; the model cannot read a checkpoint. Getting previous turns into the prompt matters just as much — that is what `_format_history()` does.

Each turn's **SQL** is sent too, not just the English answer: `ORDER BY AVG(e.salary) DESC LIMIT 1` says far more clearly than the answer does what "them" refers to.

**And the thing the checkpointer newly created:** state now survives between turns, so every field needs a declared scope. The input dict from `run_agent` is **merged over** the checkpointed state — any key missing from it carries over from the previous turn. `history` should carry over; `retry_count`, `logs` and `error` **absolutely should not** — otherwise the previous turn's 3 retries would make the next turn give up on its very first error, and the trace would show the previous question's lines. That is why `run_agent` explicitly resets the per-turn fields. That single line is the difference between a memory feature and a memory bug.

There is deliberately **no** additive reducer (`Annotated[..., operator.add]`) on `history`: nodes return `{**state, ...}`, so every node already returns the whole history — a reducer would re-append it every time and history would grow exponentially. With overwrite semantics only `synthesize_and_validate` adds a turn: the last node in the graph, which runs exactly once per turn (`generate_sql` runs again inside the retry loop — appending there would produce three entries for one turn).

## backend/tests/ — the first tests in this project

69 tests, with no API key and no database. They test the **semantics** of memory, not the quality of the model — which state carries and which resets is a question that lives entirely outside the LLM. The Gemini free tier gives 20 requests/day; spending that quota on tests that learn nothing from it is a straight loss.

`Dockerfile.test` exists because there is no local Python on this machine.

---

## HITL approval gate (Phase 3)

**Files:** `nodes.py` (`needs_approval`, `await_approval`, `after_approval`, `is_destructive`, `execute_sql`), `graph.py` (the interrupt wiring), `db.py` (`run_write`), `api/query.py` (`/api/approve`), `frontend/src/chat/Turn.jsx` (the approval card).

**What it does:** a destructive query is no longer hard-blocked — the graph pauses, shows the user the exact statement, and waits for a decision.

### Three things learned while building it

**1. A dedicated approval node was necessary.** This LangGraph version has no dynamic `interrupt()` — only static `interrupt_before=[...]`, which pauses **every time** before the named node. Putting that on `execute_sql` would pause every `SELECT` too. Making `await_approval` a separate node made the pause **conditional**: routing decides whether this turn passes through the gate at all.

**2. HITL is impossible without a checkpointer.** The graph state has to be saved somewhere between two HTTP requests — without that there is nothing to resume. So the stateless path (no `thread_id`) keeps the old hard block. **That is not a gap, it is the right behaviour:** showing an approval prompt that cannot be honoured is worse than refusing outright. Phase 4 landing before Phase 3 was not a coincidence.

**3. The generation prompt had to change, or the whole phase would be dead code.** The system prompt said "only ever write SELECT queries" — a constraint that existed **because there was no gate**. Leaving that line in after building the gate would mean destructive SQL is never generated, the gate never fires, and the phase looks like it "works" while nothing ever reaches it.

> This was caught on the very first test: "Delete all employees from HR" was asked and the model wrote a `SELECT`, skipping the gate. The prompt is now conditional on `hitl_enabled`.

### `ALLOW_WRITES` — being approved and being committed are different

At `false` (the default) an approved statement **still runs** — Postgres plans it, enforces the constraints, reports the affected rows — and then rolls back. That makes the approval flow demonstrable on a public deployment without handing any visitor the ability to empty a table.

**This is not approval theatre:** the response says plainly that it was rolled back and how many rows would have been affected. Running in a safe mode and lying are two different things.

`run_write` is kept separate from `run_sql`: `run_sql` is read-only by contract and its caller expects a result set; a write has no rows at all (`result.keys()` raises there). Merging the two is exactly how a "read-only" helper quietly starts modifying data.

### The synthesis prompt guards both directions

It used to hardcode "this system is STRICTLY READ-ONLY". After `ALLOW_WRITES=true` existed, that made it lie in the **opposite** direction: a write that genuinely committed would be reported as "nothing changed". The prompt is now conditional on the flag.

This is the same lesson as the earlier false-confirmation bug (the "removed from the HR department" lie), just mirrored — **no false confirmation, and no false reassurance either.**

The rejection answer is not generated by the LLM at all — it is a fixed policy outcome. Having the model write it would give it room to narrate its way into saying something else.

### Why 409 and not 200 or 400

Approving a thread that is not paused (a double-click, a stale tab) is neither the caller's mistake nor a server fault. Silently returning 200 would be the worst option: the user would believe their decision was applied when nothing happened.

### What was verified, and what was not

**Verified (live, against Postgres):** the gate pauses on a destructive query (`awaiting_approval: true`, empty `final_answer`), rejecting runs nothing, approving runs the statement and rolls back (2 rows reported, data intact), and approving twice returns 409.

**⚠️ Not verified:** the `ALLOW_WRITES=true` commit path was never run against the real database — it would genuinely delete rows and the demo data would be gone. That branch is covered by unit tests (with a fake `run_write`, in both directions), but not end to end. **Say this yourself in an interview.**

---

## backend/app/validators.py — the output guard

**What it does:** strips schema identifiers and leaked SQL out of the final answer, and reports what it found in `guardrail_flags`.

### Why not Guardrails AI (tried twice)

| Version | Requires | Result |
|---|---|---|
| `<= 0.5` | `langchain-core<0.3` | Conflict — we need `>=0.3` |
| `>= 0.6` | `langchain-core>=1.0` | Conflict — langgraph 0.2 requires `<0.4` |

There is no version in between. Using it would have meant a full **langchain 1.x migration** — breaking the checkpointer and graph APIs — for the sake of one validator.

**And a deterministic check is the better fit here anyway.** Schema leakage is a *syntactic* property: either the answer contains `employees.salary` or it does not. That is a job for a regex, not for judgement. Adding another LLM for it turns a deterministic check into a probabilistic one — **and then who checks that LLM.**

### The most important line: what is NOT flagged

`salary`, `name`, `role`, `budget`, `location` — these are in the schema and also in ordinary English. Flagging them would **break every correct answer.** So only things that never appear in prose are flagged:
- Qualified identifiers: `employees.salary`, `e.name`, `d.budget`
- `department_id` (a schema-only name)
- `SELECT ... FROM` (a SQL fragment)

A generic `\w+\.\w+` pattern was deliberately avoided — it matches "e.g." and every sentence boundary. The pattern is built from the schema's **real names**, which removes almost all false positives.

### Redact, do not block

A leaked schema name is low severity — killing a correct answer over it is worse for the user than the leak. **But fixing it silently would be wrong too:** the flags travel out in the API response and a line appears in the trace, so that "the guard did something" and "the guard was never needed" look different.

One exception: a whole query appearing in the answer. Cutting pieces out and showing the remainder would hand the user a partial answer that still looks trustworthy — so the whole answer is replaced.

### What is not enforced, and why

The synthesis prompt also says not to give salary figures for more than one person. **That rule cannot be made deterministic:** "Engineering averages 101750, Sales 73000" has two figures, but they are aggregates, not any individual's salary. Separating those needs semantics. Rather than **pretend** to enforce it, it is honest to say that rule stays at the prompt level.

---

## Frontend — app shell, trace rail, dashboard

**Files:** `App.jsx` (shell composition), `chat/TracePanel.jsx`, `views/Dashboard.jsx`, `components/Charts.jsx`, `Shell.css`.

**The trace rail is the most important part.** The whole project claims that the agent reads a database error and fixes its own query — and a chat bubble showing only the final answer is **exactly the view in which that claim becomes invisible.** A retry only exists on screen if the failure is visible too. That is why the trace is its own panel rather than a collapsed accordion.

**The charts are hand-rolled SVG/CSS, no library.** Two forms, four categories — a few dozen lines. Pulling in Recharts would mean ~500KB in a single-page bundle, and giving up control over exactly the things that matter here: mark geometry, label placement, theme tokens.

**The colours come from a validated categorical palette** (`--series-1..4` in `index.css`), assigned in a fixed order rather than cycled. The light and dark steps were **chosen separately**, not flipped automatically. Both modes passed the validator: worst adjacent CVD ΔE 9.1 light / 8.4 dark. In light mode the contrast falls below 3:1 — the mitigation is that **every bar carries its own value label**, so identity never rests on colour alone.

**The dashboard numbers are of two different kinds, and the UI shows the difference:**
- **Database figures** — live, from `/api/stats`
- **Eval results** — a static constant, labelled as such in the UI (`20 questions · gemini-3.5-flash-lite`). That 20-question harness takes minutes and eats most of a day's free quota; recomputing it on page load is simply not possible. Presenting old numbers as if they were live would be worse than labelling them honestly as a recorded result.

**The dashboard query is hard-coded, not generated by the agent.** The dashboard is a fixed report, not a question. Having the agent build it would mean an LLM call on every page load, non-deterministic numbers, and a panel that goes blank when the quota runs out.

**The eval chart carries its honest reading with it** — directly under the chart, not buried in a doc. Without that the headline number makes the system look better than it is: in the first two conditions the loop never fired at all.

### `result_rows` — rows in the API

`execute_sql` now also puts the rows into state in structured form (up to `MAX_RESULT_ROWS = 50`), so the UI can show a table. The cap exists because these rows are **written into the checkpointer** — without it, one "SELECT * FROM employees" would put the entire table into every conversation checkpoint.

`_serializable()` turns Postgres `Decimal` and `date` values into JSON-safe ones. That is not only for the API: the checkpointer serializes them too, so a new column type would break the API and memory at the same time.

---

## backend/app/seed.py — realistic data

**Why 10 rows were not enough.** The old dataset had 10 employees and 4 departments, and three things broke because of it:

- **The dashboard looked empty** — a bar chart with four bars does not read as a chart
- **There was no date column at all**, so the most natural dashboard question of all — "hiring trend" — could not even be asked
- **Joins never went past two tables** — the hard part of real Text-to-SQL is the multi-hop join, and that is exactly where models make mistakes

Now: **8 departments, 160 employees, 10 projects**, hire dates spread across 2020-2025, and a third table (`projects`) joined through `departments`.

**It is random, but seeded random.** `random.Random(42)` is fixed, so every machine generates exactly the same data. **This matters for the eval:** if the seed drifted, no accuracy number could be compared with a previous run, and a claim like "self-healing improved accuracy" would mean nothing.

**Salary bands are tied to roles rather than flat random** — and a manager-level role goes to only 10% of people. That makes "average salary" and "highest paid" give different answers; with flat random both answers would be pure coincidence.

**One comment did not match the code:** the hire-date spread multiplier was 380, giving ~3 years, while the comment claimed 6. It is now 700 and the data matches the comment.

---

## backend/app/conversations.py — saved conversations

**This fixes a real bug rather than adding a feature.**

Conversation memory was built in Phase 4 and did work — but the UI generated **a fresh `thread_id` on every page load**. That meant every previous conversation stayed in Postgres and became unreachable. **The data was not being deleted, it was being orphaned.** From outside it looked like "everything disappears on refresh"; from inside it was a memory feature that never looked up its own checkpoints again.

**The fix has two halves:**
1. `thread_id` now lives in `localStorage` (frontend)
2. `/api/conversations` lists them, `/api/conversations/{id}` opens one, and `DELETE` removes one

**The first version took the wrong approach, and that is worth recording.** It tried to read `checkpoint_blobs` directly with SQL — and those are **msgpack**, not jsonb. Decoding it by hand would mean copying an internal format that would break silently on the next library release. **The checkpointer knows what it wrote — so it is the thing to ask.** The thread list now comes from SQL (cheap, no deserialization) and the content from `saver.get_tuple()`.

**Sorting is on the checkpoint timestamp, not on `thread_id`** — the thread id does contain a timestamp, but it is **generated by the client**. A different client sending a different format would silently break the ordering.

**Deletion covers all three tables** (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`) — clearing only one would leave orphaned rows and recreate exactly the situation this file was written to fix.

**Restored turns look different.** Checkpointed history holds only the question, the SQL and the answer — the trace and the rows are per-turn state and get reset. So the UI says "Restored from an earlier session"; showing an empty trace would imply the run had no steps, when the truth is that they were not retained.
