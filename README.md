# Self-Healing Data Query Agent

A natural-language-to-SQL agent that autonomously detects and self-heals from SQL syntax/schema errors using a cyclical LangGraph state machine, then validates its own output before returning it to the user.

Most Text-to-SQL demos are a single LLM call: if the generated SQL is wrong, the user gets a stack trace. This agent feeds the **actual database error back into the model** and regenerates the query — up to 3 times — before giving up gracefully.

## Tech Stack

| Layer | Technology |
|---|---|
| Agent Workflow | LangGraph (Python) — `StateGraph` with conditional edges |
| Conversation memory | LangGraph `PostgresSaver` checkpointer, keyed by `thread_id` |
| LLM Inference | LangChain + Google Gemini (`temperature=0`, model set via `GEMINI_MODEL`) |
| Write safety | Human-in-the-loop approval gate (`interrupt_before`) before any modifying statement |
| Output validation | Deterministic guard on the final answer — strips schema identifiers and leaked SQL |
| Observability | LangSmith tracing (opt-in via env vars, off by default) |
| API Backend | FastAPI + Uvicorn |
| Data Store | PostgreSQL 18 (SQLAlchemy Core + psycopg2) |
| Frontend UI | React 18 + Vite, served by Nginx (`/api/` reverse proxy) |
| Containerization | Docker & Docker Compose |

## How it works

1. User asks a question in natural language (e.g. "Who earns more than 80000 in Engineering?").
2. `generate_sql` builds a `SELECT` query from a plain-text schema description injected into the prompt.
3. Anything that would modify data (`DROP`/`DELETE`/`UPDATE`/`INSERT`/`ALTER`/`TRUNCATE`) stops at an approval gate — see [Human-in-the-loop approval](#human-in-the-loop-approval). Everything else runs straight against PostgreSQL.
4. A **conditional edge** routes on the result:
   - success → synthesize
   - error and `retry_count < 3` → back to `generate_sql`, this time with the previous SQL **and** the database error in the prompt
   - error and retries exhausted → synthesize a graceful apology instead of leaking the traceback
5. `synthesize_and_validate` turns rows into a one-or-two-sentence answer, then a deterministic guard strips anything the prompt asked it not to say — qualified identifiers like `employees.salary`, schema-only column names, or leaked SQL. The prompt is a request; the guard is the guarantee.
6. The API returns the answer, the executed SQL, the result rows, `retry_count`, any `guardrail_flags`, and step-by-step trace logs for the UI.

If the request carried a `thread_id`, step 2 also receives the earlier turns of that
conversation, and step 5's answer is appended to them — see [Conversation memory](#conversation-memory).

**New here? Start with [docs/PROJECT_WALKTHROUGH.md](docs/PROJECT_WALKTHROUGH.md)** — one file with the request flowchart, how each piece was built and why, and how the whole system works today.

See [docs/TECHNICAL_SPEC.md](docs/TECHNICAL_SPEC.md) for the architecture and state schema, [docs/CODE_NOTES.md](docs/CODE_NOTES.md) for why each file/dependency exists, and [docs/INTERVIEW_NOTES.md](docs/INTERVIEW_NOTES.md) for the pitch, trade-offs, and anticipated Q&A.

## Implementation Status

Honest snapshot — docs describe what exists, roadmap items are marked as such.

- ✅ `backend/app/db.py` — Postgres engine; `departments` + `employees` + `projects` (two FKs), 160 seeded employees with hire dates, `run_sql`
- ✅ `backend/app/graph.py` — full LangGraph self-healing state machine
- ✅ `backend/app/main.py` — `GET /health`, `POST /api/query`, `POST /api/approve`
- ✅ Docker Compose (`db` + `backend` + `frontend`)
- ✅ LangSmith tracing wired (opt-in; set `LANGCHAIN_TRACING_V2=true` + an API key)
- ✅ Three-table schema with dates — questions need real JOINs, multi-hop joins, and time reasoning ("hiring trend", "tenure")
- ✅ Evaluation harness — 20 questions with gold SQL, execution-accuracy metric, retries-on vs retries-off comparison ([eval/](eval/))
- ✅ Conversation memory — LangGraph `PostgresSaver` checkpointer, per-`thread_id`, so follow-up questions can refer back ([how it works](#conversation-memory))
- ✅ Test suite — 69 tests covering memory, approval gate, output guard, data access, widget selection and Power BI export; no API key or database needed
- ✅ Human-in-the-loop approval — destructive statements pause for review instead of being blocked; `ALLOW_WRITES` decides whether an approved statement commits or runs-and-rolls-back ([how it works](docs/TECHNICAL_SPEC.md))
- ✅ Output validation — deterministic guard that strips schema identifiers and leaked SQL from the answer, reported via `guardrail_flags` ([why not Guardrails AI](docs/CODE_NOTES.md))
- ✅ React + Vite app — sidebar shell, chat with SQL and result table, live agent-trace rail, and a dashboard of database figures plus the measured eval result
- ✅ Deployment ready — single-service Docker image (FastAPI serves the API + built SPA on one URL), per-IP rate limiting, `render.yaml`, guide in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- ✅ MCP — database access goes through an MCP server over stdio when `USE_MCP=true`, direct driver otherwise ([why both](docs/TECHNICAL_SPEC.md))
- ✅ AI-generated dashboards — one sentence becomes several self-healed queries, each rendered as the widget its result shape calls for
- ✅ Power BI export — `.pbids` + Power Query scripts, DirectQuery, no credentials written to the file
- ✅ Saved conversations — the thread id survives a reload, and the sidebar lists, reopens and deletes past conversations
- ⬜ Actually deployed (no live URL yet) — remaining steps are checklisted at the top of [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- ⬜ Authentication — `thread_id` and the approve endpoint are unauthenticated; anyone holding a thread id can read or approve on it

## Project Structure

```
Dockerfile  Single-service deploy image (React build + FastAPI)
backend/    FastAPI app, LangGraph agent, Postgres checkpointer, tests
frontend/   React + Vite app — chat, agent-trace rail, dashboard
eval/       Evaluation harness, gold questions, measured results
docs/       PROJECT_WALKTHROUGH (start here), spec, code notes, interview notes, deployment
```

## Setup

```bash
cp .env.example .env   # fill in GOOGLE_API_KEY
docker compose up --build
```

This brings up three containers: `db` (PostgreSQL 18), `backend` (FastAPI + agent on :8000), and `frontend` (React via Nginx on :80). Open `http://localhost` for the chat UI; Swagger docs are at `http://localhost:8000/docs`.

If those ports are taken, set `BACKEND_PORT` / `FRONTEND_PORT` in `.env` — the compose file reads both.

## Human-in-the-loop approval

Ask for something that would change data and the agent does not refuse — it stops
and shows you the exact statement:

```bash
curl -X POST localhost:8000/api/query -H 'Content-Type: application/json' \
  -d '{"question":"Delete all employees from HR","thread_id":"demo-2"}'
# -> {"sql_query":"DELETE FROM employees WHERE department_id = (...)",
#     "final_answer":"", "awaiting_approval":true}

curl -X POST localhost:8000/api/approve -H 'Content-Type: application/json' \
  -d '{"thread_id":"demo-2","approved":true}'
# -> "The requested action would have affected two employees, but no changes
#     were made to the database."
```

**`ALLOW_WRITES` decides what "approved" means.** Left off (the default), an
approved statement still *executes* — Postgres plans it, enforces every
constraint, and reports the rows it would have touched — and is then rolled back.
That is what makes the gate demonstrable on a public URL without handing any
visitor the ability to empty the table. It is not theatre: the answer says
plainly that nothing was changed. Set it to `true` and the same approval commits.

**The gate needs the checkpointer.** Pausing and resuming spans two HTTP
requests, so the graph's state has to live somewhere in between — without a
`thread_id` there is nothing to resume from, and that path keeps the original
hard block. Offering an approval prompt that cannot be honoured would be worse
than refusing outright.

**One thing had to change for the gate to be reachable at all.** The generation
prompt used to say *"only ever write SELECT queries"* — a rule that existed
precisely *because* there was no gate. Left in place it would have meant
destructive SQL is never generated, the gate never fires, and the feature demos
as working only because nothing ever reaches it. On the gated path the model may
now write a modifying statement when the user explicitly asks for one, since a
human sees every one of them first.

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

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) to put it online for free (single Render service + Neon Postgres).

## Roadmap

Every phase below is built except where marked. The build order, and what each one
actually delivered, is in [docs/PROJECT_WALKTHROUGH.md](docs/PROJECT_WALKTHROUGH.md).

**Phases 2, 3 and 4 are built.** What each one actually delivered, and what it did not:

- **Phase 2 — Model Context Protocol** ✅ The database is reachable through an MCP server over stdio (`USE_MCP=true`); `app/data_access.py` picks the transport and the graph never knows which ran. *Still open:* this talks to our own server. The point of the protocol is that the same agent could be pointed at a third-party one without changing — that has not been demonstrated.
- **Phase 3 — Human-in-the-Loop approval** ✅ A modifying statement pauses the graph and waits for a decision, instead of being blocked outright — see [Human-in-the-loop approval](#human-in-the-loop-approval). *Still open:* the approve endpoint is unauthenticated, exactly like `thread_id`. Anyone holding the thread id can approve a write on it.
- **Phase 4 — Postgres checkpointer** ✅ Cross-session conversation memory, see [Conversation memory](#conversation-memory). *Still open:* multi-tenant isolation — one namespace per user, not just per thread.
- **Phase 5 — AI-generated dashboards** ✅ "Create a dashboard showing X" is split into questions, each runs through the same self-healing agent, and the widget for each is picked from the **shape of its result** — not by another model call, because that part is a rule rather than a judgement. Lives beside chat mode rather than replacing it. *Still open:* the plan is one shot; it cannot notice a question came back useless and ask a better one.
- **Phase 7 (next) — evaluate on Spider.** The honest limit of this project is
  schema *scale*, not data realism: three tables is small, and a hand-written
  schema description stops being possible somewhere around thirty. [Spider](https://yale-lily.github.io/spider)
  is the standard Text-to-SQL benchmark and ships labelled gold queries, so it
  answers the question this eval cannot — does an error-informed retry loop still
  help on a schema an order of magnitude larger, or does the model start failing
  *semantically* (valid SQL, wrong question) where the loop is blind? That is a
  measurement, not a feature, which is why it ranks above anything else left.
- **Phase 6 — Power BI export** ✅ A generated dashboard exports as a `.pbids` connection file plus one Power Query (M) script per widget, carrying the agent's SQL in DirectQuery mode. *Deliberately an export, not an integration:* publishing to a workspace needs an Azure AD app registration and tenant permissions this project does not have, and a button implying otherwise would be a lie.

## Positioning

Part of an **"Agentic Self-Correcting Systems"** portfolio theme alongside [Adaptive CRAG](../adaptive-crag) and [Code Guardian](../code-guardian) — same underlying idea (LLM + self-verification + autonomous correction) applied to three different failure domains: SQL *execution errors*, retrieval *relevance*, and code *defects*.
