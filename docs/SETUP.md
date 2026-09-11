# Setup Guide — PRISM INTEL

Getting the stack running from a clean machine, the loops you actually work in
day to day, and the errors this project hit — with what each one turned out to
be. If you only want to deploy it somewhere public, that is
[DEPLOYMENT.md](DEPLOYMENT.md); this file is about running it here.

---

## 1. Prerequisites

| | Why |
|---|---|
| **Docker Desktop** | The whole stack is three containers. Nothing else has to be installed — there is no local Python or Node requirement, and the test image bundles its own interpreter. |
| **A Google AI Studio key** | Free tier. Get one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). Without it the app starts and serves the dashboard and schema views, but any question fails at `generate_sql`. |
| **Git** | To clone. |

A LangSmith key is optional and covered in [section 6](#6-turning-on-tracing).

---

## 2. First run

```bash
git clone git@github.com:Nitishjha7/self-healing-sql-agent.git
cd self-healing-sql-agent

cp .env.example .env
# open .env and put the real key in GOOGLE_API_KEY

docker compose up --build
```

Three containers come up:

| Container | What it is | Default host port |
|---|---|---|
| `db` | PostgreSQL 18, seeded on first boot | `5432` (`DB_PORT`) |
| `backend` | FastAPI + the LangGraph agent | `8000` (`BACKEND_PORT`) |
| `frontend` | React build served by nginx, `/api/` proxied to the backend | `80` (`FRONTEND_PORT`) |

Open **http://localhost**. Swagger is at **http://localhost:8000/docs**.

**The API key never goes in `.env.example`.** That file is committed; `.env` is
gitignored. This is not a hypothetical — a real key was pasted into the template
once during this project and caught before the commit landed.

### If those ports are taken

Every host port is overridable, because this machine runs three agentic-AI
projects that all wanted 8000 and 5432:

```bash
# in .env
DB_PORT=5434
BACKEND_PORT=8002
FRONTEND_PORT=5174
```

Only the *host* side changes. Inside the compose network the backend still
reaches Postgres at `db:5432`, so nothing in the code cares.

---

## 3. Check it actually works

```bash
curl localhost:8000/api/health      # {"status":"ok"}
curl localhost:8000/api/meta        # what this instance is running
curl localhost:8000/api/stats       # 160 employees, 8 departments
```

`/api/meta` is the useful one — it reports the live model, Postgres version,
transport, retry budget, write mode and whether conversation memory started.
It is the same data the UI status bar shows, so if the bar looks wrong, compare
it against this endpoint rather than guessing.

Then ask a real question:

```bash
curl -X POST localhost:8000/api/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"Which department has the highest average salary?"}'
```

---

## 4. The loops you work in

**Full stack, rebuilt:**

```bash
docker compose up --build
```

**API only** — skip the frontend build when you are working on the agent:

```bash
docker compose up -d db backend
```

**Frontend only** — the React build is the slow part of a full rebuild:

```bash
docker compose up -d --build frontend
```

**Tests (69).** No API key, no database, no network — they cover the seams
(memory semantics, the approval gate, the output guard, data-access parity,
widget selection, Power BI export), not the prompts:

```bash
docker build -f backend/Dockerfile.test -t sql-agent-test backend
docker run --rm sql-agent-test
```

**Eval.** This one *does* spend quota — 20 questions × 2 conditions is 40+ LLM
calls, and the free tier is small:

```bash
docker compose run --rm --no-deps -v "$PWD/eval:/app/eval" \
  backend python -m eval.run_eval --stale-schema
```

Results land in `eval/results*.json`; the written-up numbers are in
[eval/RESULTS.md](../eval/RESULTS.md).

---

## 5. Resetting the database

The seed is deterministic (`random.Random(42)`), so a reset always produces the
same 160 employees, 8 departments and 10 projects. That matters — if the seed
drifted, no eval number could be compared with a previous run.

```bash
docker compose down -v      # drops the pgdata volume
docker compose up --build   # recreates and reseeds
```

`init_db()` also detects two older schema shapes and rebuilds automatically, so
an existing volume from an earlier version does not need this by hand.

---

## 6. Turning on tracing

Optional, off by default, and no code path depends on it:

```bash
# in .env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=<key from smith.langchain.com>
LANGCHAIN_PROJECT=self-healing-sql-agent
```

Restart the backend and every node's prompt, response and latency shows up in
LangSmith. The trace worth looking at is a **retry**: ask something against the
stale schema and you can watch the second `generate_sql` call arrive with the
Postgres error text in its prompt. That is the whole project in one screen.

---

## 7. Errors this project actually hit

These are not hypotheticals. Each one cost real time, and the fix is recorded so
it costs nothing the second time.

### `Port number was not a decimal number` / port already allocated

Another project on this machine holds the port. Set `DB_PORT`, `BACKEND_PORT` or
`FRONTEND_PORT` in `.env` — see [section 2](#if-those-ports-are-taken).

### Postgres 18 refuses to start on an existing volume

PostgreSQL 18 changed the expected mount point. The compose file mounts
`/var/lib/postgresql`, **not** `/var/lib/postgresql/data` as PG 15–17 did. If you
are coming from an older volume:

```bash
docker compose down -v
docker compose up --build
```

### `404 models/gemini-… is not found`

Google retired two model ids during this project's life. That is exactly why the
model is an environment variable and not a literal. List what your key can
actually see:

```bash
curl "https://generativelanguage.googleapis.com/v1beta/models?key=$GOOGLE_API_KEY"
```

Then set `GEMINI_MODEL` in `.env` to one of them. Note that the docs and
`eval/RESULTS.md` attribute their numbers to `gemini-3.5-flash-lite`; if you run
a different model, the numbers are no longer comparable.

### `429` / quota exhausted

The free tier is roughly 15 requests per minute, and some models allow only 20 a
day. Two things spend it fast:

- **the dashboard builder** — one request is `MAX_WIDGETS` full agent runs, 6-9
  LLM calls
- **the eval harness** — 40+ calls per full sweep (it has exponential backoff
  built in for this reason)

The app's own per-IP rate limit (`RATE_LIMIT_REQUESTS`, default 5 per 60s) exists
to stop one visitor doing this to a public demo.

### MCP silently falls back to the direct driver

Expected, and by design. With `USE_MCP=true` the backend logs

```
MCP unavailable (…) — falling back to the direct driver.
```

and carries on. Check `/api/meta` → `data_access` to see which transport is
actually live. A silently failing MCP path would be the worst outcome, so it
always says so.

### `guardrails-ai` will not install

It cannot, on this stack, and it is not supposed to be there. `<=0.5` wants
`langchain-core<0.3`, `>=0.6` wants `>=1.0`, and this project is on langgraph
0.2 / langchain 0.3. The output guard is deterministic instead — the reasoning is
in [CODE_NOTES.md](CODE_NOTES.md) and the trade-off is a fair interview question.

---

## 8. Where to go next

| | |
|---|---|
| [PROJECT_WALKTHROUGH.md](PROJECT_WALKTHROUGH.md) | Start here — the flowchart, and what was built in what order |
| [CODE_QA.md](CODE_QA.md) | Hard questions about this code, with answers |
| [ROADMAP.md](ROADMAP.md) | What is built, what is not, and what is worth doing next |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Putting it online for free |
