# Deployment Guide — Render + Neon

Goal: **one public URL** you can put in a portfolio, that **always works**, and is **free**.

---

## ✅ What is left — the full checklist

The code is ready and has been tested locally. These steps have to be done by hand:

### 1. Deploying (~30-40 min) — the actual remaining work

- [ ] Tests pass: `docker build -f backend/Dockerfile.test -t sql-agent-test backend && docker run --rm sql-agent-test`
- [ ] Free account on **Neon** → Postgres project → copy the connection string (Step 1 below)
- [ ] **Render** → Web Service → connect the GitHub repo → Docker runtime (Step 2)
- [ ] Set the environment variables: `DATABASE_URL`, `GOOGLE_API_KEY`, `GEMINI_MODEL`, `RATE_LIMIT_*`
- [ ] Verify the deploy — open the URL, ask a question (Step 3)
- [ ] Add an **UptimeRobot** monitor on a 10-minute interval (Step 4) — **do not skip this**, without it the service falls asleep
- [ ] Add the live URL to the README

### 2. Look at one LangSmith trace yourself (5 min) — small but important

Tracing is wired (`LANGCHAIN_TRACING_V2=true` plus a key), but **not one trace has actually been looked at yet.**

- [ ] Set `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_API_KEY` in the local `.env`
- [ ] Run a query that **actually fails and retries** — the easiest way:
      `docker compose run --rm --no-deps -v "<repo>/eval:/app/eval" backend python -m eval.run_eval --stale-schema --limit 3 --retries 3`
- [ ] Open the project on [smith.langchain.com](https://smith.langchain.com) and expand one run
- [ ] **Look at the retry chain** — each `generate_sql` call, its rendered prompt with the injected error, the raw response, latency, tokens
- [ ] Take a screenshot (for the portfolio and the interview)

**Why it matters:** saying "I look at traces" in an interview and then freezing on "what does it look like?" is a bad moment. **Wiring something up and reading a trace are two different claims.**

### 3. A Guardrails AI validator node (~1 hour) — OPTIONAL

Safety is currently prompt-level, and every doc says so honestly. The project is defendable without this.

- [ ] Add `guardrails-ai` back at a version compatible with `langchain-core>=0.3` (the old `0.5.10` conflicted — see [CODE_NOTES.md](CODE_NOTES.md))
- [ ] A separate validator node after `synthesize_and_validate`
- [ ] Change `[Planned]` → `[Implemented]` in the docs and remove that entry from the honesty checklist in INTERVIEW_NOTES

> **There is not much value here.** Guardrails feels bolt-on in this project, because the DB error already provides deterministic ground truth. In Adaptive CRAG it is a *core feature* (verifying a grounded answer) — spend the time there instead.

### 4. Sync the docs after deploying

- [ ] Change `⬜ Actually deployed` → `✅` in the README and ROADMAP, with the live URL
- [ ] Read the [honesty checklist](INTERVIEW_NOTES.md) in INTERVIEW_NOTES and confirm every claim is still true

---

| Piece | Host | Notes |
|---|---|---|
| App (UI + API, one service) | **Render** free web service | Deployed from Docker, a single URL |
| Database | **Neon** free Postgres | No card needed, wakes in ~500ms |
| Keep-alive | **UptimeRobot** free | Stops the service from sleeping |

---

## Architecture — one service, one URL

The root [`Dockerfile`](../Dockerfile) builds in two stages: first the React app (`npm run build`), then a Python image into which those built files are copied as `static/`. FastAPI serves both:

```
https://self-healing-sql-agent.onrender.com
  ├─ /              → React chat UI
  ├─ /api/query     → agent (rate-limited)
  ├─ /api/health    → health check
  └─ /health        → same, for uptime pingers
```

**Why one service and not two:** a split deployment means configuring CORS, deploying in two places, and keeping both warm. Serving from the same origin removes all three problems. Local `docker-compose` still serves the frontend through nginx — `backend/Dockerfile` exists for that.

## ⚠️ Render free tier — one thing to know up front

A Render free web service **sleeps after 15 minutes of inactivity**, and takes **50+ seconds** to wake. Without a fix: a recruiter opens the link, sees a blank screen, and closes the tab.

**The fix (Step 4):** UptimeRobot pings `/health` every 10 minutes, so the service is never idle for 15. The free tier gives 750 hours/month — a full month for one service. `/health` is deliberately exempt from the rate limiter, so the pinger is never throttled.

**Do not use Render's free Postgres** — it expires after 30 days and the portfolio link dies quietly. Use Neon.

---

## Step 1 — Database (Neon)

1. Free account on [neon.tech](https://neon.tech) → new project (region Singapore, closest to India).
2. Copy the connection string:
   ```
   postgresql://user:pass@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```
3. No tables to create by hand — `init_db()` creates and seeds them on startup.

> **Do not remove** `?sslmode=require` — Neon rejects plain connections and the app will not start.

> **Conversation memory runs on this same database.** `PostgresSaver` creates its own checkpoint tables (`saver.setup()` on startup, idempotent) — no separate service or migration needed. If Neon is unreachable the app does not crash; memory switches off quietly and the API returns `memory_active: false`. Confirm it after deploying by asking a follow-up question (Step 3).

## Step 2 — Deploy (Render)

[dashboard.render.com](https://dashboard.render.com) → **New → Web Service** → connect the GitHub repo.

| Setting | Value |
|---|---|
| Language / Runtime | **Docker** |
| Dockerfile Path | `./Dockerfile` |
| Docker Build Context | `.` (repo root) |
| Instance Type | **Free** |
| Region | Singapore |
| Health Check Path | `/health` |

> Pick the root `Dockerfile`, not `backend/Dockerfile` — that one is for local compose and does not build the frontend.

**Environment variables** (in the Render dashboard):

| Key | Value |
|---|---|
| `DATABASE_URL` | the Neon string, with `?sslmode=require` |
| `GOOGLE_API_KEY` | from [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` |
| `RATE_LIMIT_REQUESTS` | `5` |
| `RATE_LIMIT_WINDOW` | `60` |

Do **not** set `PORT` — Render injects it, and the Dockerfile reads it.

The repo also has a [`render.yaml`](../render.yaml) — deploying via a Render Blueprint picks these settings up automatically (secrets still have to go in the dashboard).

Once deployed you get a URL like `https://self-healing-sql-agent.onrender.com`. That URL is **permanent** — it stays the same across redeploys.

## Step 3 — Verify

```bash
curl https://YOUR-APP.onrender.com/health

curl -X POST https://YOUR-APP.onrender.com/api/query \
  -H "Content-Type: application/json" \
  -d '{"question":"Which department has the highest average salary?"}'
```

Then open the URL in a browser — the chat UI should appear. Ask a question and open "Show SQL & steps" to see the trace.

**Check conversation memory too** (this is genuinely tested for the first time on the deploy, because Neon is not the local Postgres):

- [ ] Ask "Which department has the highest average salary?"
- [ ] Then follow up with **"how many people work there?"** — if it understands Engineering, memory is working
- [ ] Or via the API: the response should carry `memory_active: true` when a `thread_id` was sent

If `memory_active: false`, look for `Checkpointer setup failed` in the Render logs — it is usually `DATABASE_URL` or a Neon connection limit.

**Check the approval gate too** (it also depends on the checkpointer, so if memory failed this is quietly off as well):

- [ ] Ask "Delete all employees from HR" → the response should carry `awaiting_approval: true` with an empty `final_answer`
- [ ] The UI should show an approval card with the pending `DELETE` statement
- [ ] **Approve** it → the answer should say plainly that it was rolled back and how many rows it would have affected
- [ ] Confirm the data really did not change (`ALLOW_WRITES` is off)

## Step 4 — Keep-alive (do not skip this)

Without it the rest is pointless — the service sleeps and the demo keeps taking 50 seconds.

1. Free account on [uptimerobot.com](https://uptimerobot.com).
2. **Add New Monitor**:

   | Field | Value |
   |---|---|
   | Monitor Type | HTTP(s) |
   | Friendly Name | SQL Agent |
   | URL | `https://YOUR-APP.onrender.com/health` |
   | Monitoring Interval | **10 minutes** |

Render sleeps after 15 minutes idle, so a 10-minute ping always stays ahead. Bonus: if the app ever goes down you get an email — you find out before an interview does.

---

## Environment variables — the full list

| Variable | Required? | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | ✅ | localhost | Neon string with `?sslmode=require` |
| `GOOGLE_API_KEY` | ✅ | — | Gemini key |
| `GEMINI_MODEL` | — | `gemini-3.5-flash-lite` | If a model is deprecated, change it here, not in the code |
| `RATE_LIMIT_REQUESTS` | — | `5` | Per IP |
| `RATE_LIMIT_WINDOW` | — | `60` | Seconds |
| `ALLOWED_ORIGINS` | — | `*` | Same-origin in the single-service image, so not needed. Set the frontend origin for a split deploy |
| `ALLOW_WRITES` | — | `false` | Whether an approved write commits or runs and rolls back. **Keep it `false` on a public demo** — otherwise any visitor can approve `DELETE FROM employees` and empty the table. The approval flow is fully visible even at `false` |
| `DISABLE_CHECKPOINTER` | — | unset | Set to `1` to turn conversation memory off. Normally leave it alone — memory should run. **Note: this also turns off the HITL approval gate**, because resuming an interrupt needs a checkpointer |
| `CHECKPOINTER_POOL_SIZE` | — | `5` | The Neon free tier connection limit is small; do not raise it above 5 |
| `HISTORY_TURNS_IN_PROMPT` | — | `3` | How many previous turns go into the prompt |
| `LANGCHAIN_TRACING_V2` | — | `false` | `true` → traces go to LangSmith |
| `PORT` | — | injected | Render provides it, do not set it yourself |

---

## Rate limiting — why it matters

Without a per-IP rate limit on a public demo, **the API key burns out.** The Gemini free tier gives the whole project ~15 requests/minute — shared across every visitor. One bot, or one curious recruiter asking 20 questions, exhausts the quota and everyone after that gets an error.

[`app/ratelimit.py`](../backend/app/ratelimit.py) applies a per-IP sliding window (5 questions/minute by default), and both `/health` routes are exempt.

**A known limitation, stated honestly:** the limiter is in-memory — counters reset on restart, and with multiple replicas each process keeps its own count. For a single-container demo that is the right trade-off; at scale it needs Redis. **Say this yourself in an interview** — knowing the trade-off is the actual point.

---

## After deploying — checklist

- [ ] The UptimeRobot monitor is running (10-min interval)
- [ ] Rate limiting works — send 6 requests quickly, expect a 429
- [ ] `.env` was not committed — `git ls-files .env` should be empty
- [ ] The Neon connection string is not in any commit
- [ ] The live URL is in the README
- [ ] Open the URL once before an interview to check it

## Troubleshooting

| Problem | Cause |
|---|---|
| The app never starts | `?sslmode=require` is missing from `DATABASE_URL` |
| It deploys but returns 502 | Render's `$PORT` was not bound — confirm the root `Dockerfile` is being used |
| The UI loads but a query 500s | Usually the Gemini quota (429 upstream). Check the Render logs |
| The first request takes 50 seconds | The service had gone to sleep — check the UptimeRobot monitor |
| JSON appears instead of the UI | The wrong Dockerfile (`backend/Dockerfile`) was selected — it does not build the frontend |
| Build fails: frontend not found | The Docker build context must be `.` (repo root), not `backend` |
