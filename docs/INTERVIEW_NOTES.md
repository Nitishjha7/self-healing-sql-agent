# Self-Healing SQL Agent — Complete Interview Prep

*Author: Nitish | Stack: LangGraph + LangChain + Gemini + FastAPI + PostgreSQL 18 + Docker + React*

**What this doc is for:** to have the "why" written down behind every technical choice, so that whatever gets asked in an interview can be defended — and "that's how the tutorial did it" never has to be the answer.

---

## Table of Contents
1. The 30-Second Pitch
2. The Problem (Why This Project Exists)
3. Is This Real or Just a Portfolio Toy?
4. What the System Actually Does (Full Flow)
5. Architecture Overview
6. Core Features & USPs (Deep Dive)
7. **Every Design Decision, Defended** ← the important one
8. Limitations & Mitigations
9. How to Present This in an Interview
10. Anticipated Interview Questions — Technical · **Credibility** · Product
11. Positioning Alongside My Other Projects
12. Demo Strategy
13. One-Liner for Resume/LinkedIn
14. Quick Reference — AgentState Schema
15. Honesty Checklist (what NOT to claim)
16. How strong this project is — an honest assessment

---

## 1. The 30-Second Pitch

> "Most Text-to-SQL demos are one LLM call — if the generated SQL is wrong, the user gets a stack trace. My agent treats a database error as a *signal*, not a failure. When a query fails, the agent feeds the exact Postgres error message plus the SQL that produced it back into the model and regenerates a corrected query, up to three times. It's built as a LangGraph state machine with a conditional edge, so the retry is an actual cycle in the graph — the model sees what broke and fixes that specific fault, instead of just being asked the same question again and hoping for a different sample."

In one line: *"a SQL agent that reads its own mistake and fixes it — not a blind retry, but error-informed repair."*

**Rule:** lead with the pitch, not the tech. Start from the failure mode, not from a feature list.

---

## 2. The Problem (Why This Project Exists)

Naive Text-to-SQL rests on one assumption: **the LLM will write correct SQL the first time.** That breaks in three places:

1. **Schema mismatch** — the model guesses a column name (`salery`, `emp_name`) that does not exist.
2. **Dialect drift** — the model writes SQLite/MySQL syntax when the database is Postgres.
3. **Ambiguous phrasing** — does "top earners" mean `LIMIT` or `WHERE salary > avg`? The first guess can be wrong.

In all three cases the database returns a **precise, structured error message** — and the naive pipeline throws it away. That error is the most valuable feedback signal available. This project does not let it go to waste.

---

## 3. Is This Real or Just a Portfolio Toy?

**If asked, be honest — that is what builds credibility.**

The pattern is real and published:
- **Self-Refine** (Madaan et al., 2023) — the model critiques its own output and iterates.
- **Reflexion** (Shinn et al., 2023) — putting verbal feedback into memory to improve the next attempt.
- **Text-to-SQL execution-guided decoding** — it is established in the literature that execution feedback substantially improves accuracy.
- LangGraph's own cookbook has a SQL agent with error correction as a reference architecture.

Production Text-to-SQL systems (enterprise BI copilots) all do some form of "generate → execute → on error, repair".

**Positioning:** *"I am not claiming a new algorithm. I am showing that I know why naive Text-to-SQL fails, and that I can build the agentic control loop for it from scratch in LangGraph — rather than making one `SQLDatabaseChain` call."*

That line matters, because LangChain ships a ready-made `SQLDatabaseChain`. An interviewer may ask "why didn't you use that?" — the answer is in Section 7.

---

## 4. What the System Actually Does (Full Flow)

1. The user asks a question in natural language.
2. **`generate_sql`** — sends the plain-text schema description plus the question to Gemini (temperature 0) and extracts the SQL from the response (stripping any markdown fence).
3. **`execute_sql`** — first the destructive-keyword guard (`DROP`/`DELETE`/`UPDATE`/`INSERT`/`ALTER`/`TRUNCATE`), then the query runs on Postgres.
4. **`should_retry`** (a conditional edge) — one of three routes:
   - **`success`** → synthesize
   - **`retry`** (there is an error and `retry_count < 3`) → back to `generate_sql`, with **the previous SQL plus the exact database error** now in the prompt
   - **`give_up`** (retries exhausted) → synthesize, but with a graceful apology
5. **`synthesize_and_validate`** — turns the rows into a one- or two-line natural answer, under a system prompt that forbids revealing raw table/column names.
6. The API returns: `final_answer`, `sql_query`, `retry_count`, and the full `logs` array (a node-by-node trace).

---

## 5. Architecture Overview

```
React + Vite Frontend  [Implemented]
  |-- Chat UI
  |-- Trace rail (logs array)
  \-- Retry-count badge
                    |
                    v
FastAPI Backend  (POST /api/query, GET /health)
                    |
                    v
LangGraph StateGraph  (AgentState threaded through every node)

     generate_sql  <------------------+
          |                           | "retry"
          v                           | (error AND retry_count < 3)
     execute_sql --[should_retry]-----+
          |     \
 "success"|      \ "give_up"
          v       v
     synthesize_and_validate --> END
                    |
                    v
              PostgreSQL 18
     departments <--FK-- employees  (seeded)
```

**Why this matters in an interview:** it shows that the orchestration layer (LangGraph), the data layer (Postgres/SQLAlchemy) and the API layer (FastAPI) are kept separate, and wired together with *conditional* control flow rather than a linear pipeline.

---

## 6. Core Features & USPs (Deep Dive)

### 6.1 Error-Informed Regeneration (the real USP)
On a retry the agent does **not send the same prompt again**. The new prompt contains: the schema, the question, the SQL that failed, the verbatim database exception, and "fix this". That is **reflection**, not **resampling**.

**Why it matters:** at temperature 0, sending the same prompt again produces literally the same output. Without new information a retry is meaningless. The error message is that new information.

> **Remember this line:** *"At temperature 0 a blind retry is meaningless — same input, same output. A retry only works if something in the prompt is new. That new thing is the database's error message."*

### 6.2 A Cyclic Graph, Not a Loop
The retry is implemented with LangGraph's `add_conditional_edges` — `should_retry` reads the state at runtime, decides which node is next, and can go back to `generate_sql`.

**Why it matters:** this is architecturally different from a `for` loop — the attempt history lives in the state object, each node's execution can be inspected separately, and plugging in a HITL interrupt or a checkpointer later is trivial (both are graph-level LangGraph features that a raw loop simply does not have).

### 6.2a Measured, Not Assumed
The eval harness (`eval/`) computes execution accuracy over 20 questions and isolates the loop's contribution by running `MAX_RETRIES=0` vs `3`. **On the production schema the delta came out at 0% — because the loop never fired once (`avg retries = 0.00`).** That result is not hidden; it is written up in full in `eval/RESULTS.md`.

**Why it matters:** this is what separates you from 90% of candidates. Most people never measure their system; those who do only show the good number. "I measured it, the delta was 0, and I know exactly why" demonstrates engineering judgement, not marketing.

### 6.3 Graceful Degradation
When retries are exhausted the user does not get a raw `psycopg2.errors.UndefinedColumn` traceback — they get a clean apology. Failure is a designed path, not a crash.

### 6.4 Read-Only Enforcement
The destructive-keyword guard runs **before** the database call, and sets `retry_count` to max — because "don't write a DELETE" is not fixed by retrying; it is a policy rejection, not an error.

### 6.5 Full Execution Trace
Every node appends to the `logs` list, which is threaded through the state and returned in full in the API response. The frontend turns it into a timeline: `Generating SQL → Execution failed: column "salery" does not exist → Retry 1 → Generated SQL → Execution succeeded, 3 rows`.

**Why it matters:** this is not a black box. Showing self-healing *happening* on screen is the strongest moment in an interview.

---

## 7. Every Design Decision, Defended

This section is the core of the doc. Each row: what was done, why, and what it costs.

### 7.1 Orchestration

| Decision | Defence | Cost / Trade-off |
|---|---|---|
| **LangGraph, not a LangChain chain** | I need branching at runtime — the execution result decides the next step. A chain is linear; you cannot build a cycle in it. | A little more boilerplate — nodes and edges have to be wired explicitly. |
| **LangGraph, not a plain `for` loop** | A loop would retry, but a state machine keeps the attempt history structured in the state, makes the trace inspectable node by node, and gives me the HITL interrupt and the checkpointer (Phases 3/4) — graph-level features a loop simply does not have. | A library dependency, and a learning curve for a new developer. |
| **Did not use the ready-made `SQLDatabaseChain`** | It is a black box — I cannot customise the error-repair prompt, expose the trace, or inject a destructive guard. Building the control loop myself was the entire point. | More code to write; if I only wanted the feature, the built-in would have been faster. |
| **3 nodes, not 5** | Each node has one clear responsibility (generate / execute / synthesize). Splitting further would add boilerplate, not semantics. | `synthesize_and_validate` does two things — validation became its own deterministic module (`validators.py`) rather than a separate node. |

### 7.2 LLM

| Decision | Defence | Cost / Trade-off |
|---|---|---|
| **Gemini Flash (currently `gemini-3.5-flash-lite`)** | A usable free tier (this is a portfolio project, not a funded product), fast on short structured outputs, and it reliably follows "give me only SQL, no explanation" — which keeps the parser simple. | Vendor-specific rate limits. Mitigation: it sits behind LangChain's chat interface, so swapping providers is a one-line change in `_llm()`. The model name is an env var, because Google retired two model ids during this project. |
| **`temperature=0`** | SQL generation should be deterministic — the same question should give the same query. Creativity is a bug here, not a feature. And it is required for reproducible demos and evals. | If the model gets stuck on one particular query there is no sampling escape. That is why a retry adds *new context* (the error), not temperature. |
| **One LLM instance for both nodes** | Generation and synthesis are both short, structured, low-creativity tasks — a separate model gave no measurable gain, only another dependency and more cost. | If synthesis ever needs more nuance, a separate larger model could be used — right now that would be over-engineering. |
| **Extracting SQL with a regex (`_extract_sql`)** | The LLM sometimes adds a ` ```sql ` fence or a line of explanation regardless of the prompt. This is defensive parsing — never trust LLM output. | Structured output (function calling / JSON mode) would be more robust. This is a conscious simplicity choice; if the output format turned out flaky I would switch to structured output. |

### 7.3 Prompting

| Decision | Defence | Cost / Trade-off |
|---|---|---|
| **Injecting the schema into the prompt as plain text** | The LLM has no direct connection to the database — it has to be told the schema. Plain text, because I can put *semantic* hints in it (example department values like 'Engineering', 'HR') that raw DDL does not carry. It also keeps the prompt token cost fixed and predictable. | If the schema changes, the description has to be updated by hand. On a large schema a hand-written description will not scale — that needs introspection plus retrieval (only the relevant tables). |
| **Both the previous SQL and the error in the retry prompt** | The error alone is not enough — the model has to see *what it wrote* that failed, otherwise it can repeat the mistake. Only together do they become actionable feedback. | A longer prompt, slightly more tokens. |
| **"Only ever write SELECT queries" in the system prompt** | The first layer of defence in depth — stop the model before it writes a destructive query, and leave the code guard as a backstop. | A prompt-level rule can be bypassed by prompt injection. Hence the code-level guard too, and a DB-level read-only role in production. |
| **A schema-leakage ban in the synthesis prompt** | The answer should say "annual salary", not `employees.salary`. Exposing the internal schema is information disclosure — it hands an attacker a map. | Prompt-level enforcement, not a guarantee. `validators.py` now makes the leakage half of it deterministic. |

### 7.4 Retry Policy

| Decision | Defence | Cost / Trade-off |
|---|---|---|
| **`MAX_RETRIES = 3`** | Genuine syntax/schema mistakes get fixed on the first or second retry once the model sees the error. Anything still failing after three is almost always a **semantic** failure (the question is not answerable) — and raising the limit only burns tokens and latency for the same result. This is a deliberate cost/latency ceiling. | A genuinely hard query that would have succeeded on the 4th attempt is missed. That is why it is a constant — the eval harness sweeps it and justifies the number. |
| **`retry_count = MAX_RETRIES` on a keyword block** | A destructive query is a **policy rejection**, not a syntax error — retrying is pointless, the model would write the same query again. Exiting immediately is correct. | It looks a little hacky (using the retry counter for control flow). A cleaner design would be a separate `blocked: bool` state field — a known refactor. |
| **An apology on failure, not a traceback** | Handing the raw exception to the user is both an information leak and bad UX. | The error is needed for debugging — so it stays in `logs`, just not in the user-facing answer. |

### 7.5 Data Layer

| Decision | Defence | Cost / Trade-off |
|---|---|---|
| **PostgreSQL, not SQLite** | SQLite's type affinity is so permissive that many *wrong* queries succeed — meaning the self-healing loop never gets the errors it was built for. Postgres's strict typing and precise error messages (`column "salery" does not exist`) are exactly the high-quality feedback signal the retry prompt depends on. And production would be Postgres anyway. | Another container, another moving piece — SQLite would be file-based, zero setup. Docker Compose absorbed that cost for the demo. |
| **Two tables with a FK, not one flat table** | On a flat table every question became a single-table `WHERE` filter — which the model gets right on the first attempt almost every time, meaning **the self-healing loop had nothing to heal** and the project's core USP never fired in a demo. With the FK the model has to infer the join, and getting a join wrong is the most common real Text-to-SQL failure — producing exactly the precise Postgres error the retry prompt consumes. | Two tables is still small. On a 50-table schema the description will not fit in the prompt — that needs schema retrieval. |
| **Stating explicitly in the schema description that the join is mandatory** | Just listing columns lets the model assume `employees` might also carry a department name. Saying plainly that the column does not exist eliminates a whole class of hallucinated queries. The description also carries example values and a relationship line — none of which come from raw DDL introspection. | If the schema changes, the description has to be updated by hand. |
| **Auto-rebuilding an old schema (`_needs_rebuild`)** | The data is only seed data, so drop-and-rebuild is safe — and it means `docker compose up` works against an existing Docker volume with no manual step. The demo has to stay reproducible. | This is not a production migration strategy — that would be Alembic. The docs say so explicitly. |
| **SQLAlchemy Core (`text()`), not ORM models** | The agent writes dynamic SQL itself — I do not need fixed declarative models, only raw execution and connection pooling. An ORM would be pure overhead here. | No type safety — but the queries are LLM-generated and unknown at compile time anyway. |
| **`pool_pre_ping=True`** | After a container restart or an idle timeout, the first query on a stale connection fails. Pre-ping handles that silently. A small flag that shows production awareness. | One small round-trip per checkout. |
| **Seeding on startup** | The demo must be reproducible — clone, `docker compose up`, query immediately. A manual migration step breaks the demo. | The seed is idempotent (a `COUNT(*) == 0` check), but this is not a production migration strategy — production would use Alembic. |

### 7.6 API & Infra

| Decision | Defence | Cost / Trade-off |
|---|---|---|
| **Exposing `logs` in the API response** | Explainability *is* the product. The user should see what the agent thought, what failed, and how it was fixed — otherwise it is a black box that is sometimes wrong. | Internal error messages reach the client. Fine for an internal demo; a public product would need to sanitise or gate the logs. |
| **`retry_count` in the response** | It is the system's own health metric — consistently high retries mean the prompt or schema description needs work. In a demo it is also the number that *proves* self-healing. | None. |
| **CORS via `ALLOWED_ORIGINS`, default `*`** | For local dev — the frontend is on a different container/port. **This is a consciously known issue** and is tightened to a specific origin before deploying. | A security issue if shipped as-is. Which is why it is explicitly flagged in both the README and the spec. |
| **LangSmith tracing, toggled by env var** | Two observability layers, deliberately: `logs` is a **product** feature (it goes out in the API response and drives the UI's explainability), LangSmith is a **developer** tool (raw prompts, token cost, per-node latency — none of which should ever reach the client). There is not one line of tracing code in the application — LangChain's callback system reads the env vars and instruments everything itself. | A dependency on an external service. Hence the `false` default — the repo runs without a LangSmith account, at zero overhead. |
| **A Postgres `healthcheck` + `depends_on: service_healthy`** | The backend runs `init_db()` on startup — if Postgres is not ready it crashes. This makes the race deterministic. | Slightly slower startup, because the backend waits. The right trade-off. |
| **Requirements before code in the Dockerfile** | Layer caching — a code change does not re-run `pip install`. It saves minutes on every rebuild. | None, this is standard practice. |
| **`.env.example` committed, `.env` not** | Secrets never go in the repo. The example file says which vars are needed without leaking values. | None. |

---

## 8. Limitations & Mitigations

**Say these yourself** — it shows maturity. Do not make the interviewer hunt for them.

### ~~Limitation 1 — A single flat table~~ ✅ FIXED
It is now `departments` + `employees` with a FK, so the model has to infer the join. **But state the honest scope:** there are three tables, not twenty. A real enterprise schema has 50+ tables where the schema description does not even fit in the prompt — that needs schema retrieval (selecting only the relevant tables). Three tables prove join reasoning, not schema *scale*.

### ~~Limitation 2 — No measured accuracy~~ ✅ FIXED
The eval harness exists — 20 questions with gold SQL, an execution-accuracy metric, and a `MAX_RETRIES=0` vs `3` comparison. **Honest scope:** 20 questions is a small set on a single schema — that gives direction, not statistical significance. A bigger claim needs more questions and multiple schemas. Say this too: the numbers are from one model, so it is the delta of *this* architecture with *this* model — not a universal claim.

### ~~Limitation 3 — Guardrails AI is not wired~~ ✅ REPLACED
Guardrails AI could not be used at all (a hard dependency conflict in both directions — see CODE_NOTES). A **deterministic** output guard (`app/validators.py`) took its place, and it is the better fit here anyway: schema leakage is syntactic, so it is a regex problem, not a judgement problem.
**Honest scope:** it enforces identifier and SQL leakage. It does **not** enforce the "don't give several people's salaries" rule, because that cannot be separated from aggregates without semantics.

### Limitation 4 — The keyword guard is naive
It is a substring match, so a legitimate query like `WHERE comment LIKE '%updated%'` also gets stopped.
**Mitigation:** it is a conservative fail-safe (a false positive is better than a false negative). The correct production answer is a database-level read-only role — that cannot be bypassed by prompt injection. This is the first layer of a layered defence, not a solution on its own.

### ~~Limitation 5 — The graph is rebuilt on every request~~ ✅ FIXED
Compiled graphs are now cached per checkpointer mode. This mattered more once the checkpointer existed: a `PostgresSaver` holds a connection pool, and a new pool per request is a connection leak.

### ~~Limitation 6 — No conversation memory~~ ✅ FIXED
A Postgres `PostgresSaver` checkpointer, per `thread_id`, so follow-ups like "and in Marketing?" work.
**Honest scope:** `thread_id` is client-generated and unauthenticated — fine for a single-user demo, not for real use.

---

## 9. How to Present This in an Interview

**Order:**
1. **Problem first (15 sec)** — naive Text-to-SQL breaks on one wrong query, and the database's error is wasted.
2. **Solution overview (30 sec)** — the pitch from Section 1.
3. **2-3 deep dives**, chosen to fit the interviewer:
   - *Agentic/systems interviewer* → conditional edges, the cyclic graph, state threading
   - *ML/LLM interviewer* → error-informed prompting vs blind resampling, the logic of temperature 0
   - *Backend interviewer* → FastAPI layering, Docker healthcheck ordering, connection pooling
   - *Product interviewer* → the cost/latency trade-off of the retry budget, explainability
4. **Volunteer one trade-off** (Section 7).
5. **Limitations + mitigations** (Section 8) — a strong closer.

**Golden rules:**
- Never open with "I used LangGraph" — open with the failure mode it fixes.
- Tie every technical choice to an outcome (cost, latency, reliability, debuggability).
- Say the trade-off before you are asked for it.

**The tech-to-outcome pattern (learn it):**
> "I built the retry as a LangGraph conditional edge rather than a `for` loop, and not to look fancy. A loop would retry, but the attempt history would not be structured in the state, the trace could not be inspected node by node, and adding a HITL approval pause or cross-session memory — both graph-level LangGraph features — would have demanded a full rewrite later. I spent an extra day of wiring so that Phases 3 and 4 became one node each."

---

## 10. Anticipated Interview Questions

> **If you read only one subsection, read "Credibility".** Those are the questions
> that can do the most damage and that people prepare for the least.

### Technical

**Q: Why LangGraph and not a plain LangChain chain?**
A: I need branching at runtime — the execution result decides which node runs next, and I need to go *back* to the generation node. A chain is linear; a cycle is not possible in it. LangGraph's `StateGraph` gives conditional edges, and the state object threads the whole execution trace through every node.

**Q: Isn't this just a `for` loop with a fancier name?**
A: The behaviour looks the same today, the architecture does not. Three concrete differences: the attempt history is structured in the state object (in a loop it would be local variables), each node's execution can be inspected, logged and tested separately, and the graph-level LangGraph features — HITL approval via `interrupt_before`, cross-session memory via the checkpointer — come for free. A loop would need a rewrite for all three.

**Q: `SQLDatabaseChain` exists — why not use it?**
A: Because that control loop *is* the project. In `SQLDatabaseChain` I cannot customise the error-repair prompt, expose the execution trace, or inject a destructive guard. If I only wanted the feature the built-in would have been faster — I wanted to demonstrate the mechanism.

**Q: How does the retry actually work? Do you send the same prompt again?**
A: No, and this is the most important detail. At temperature 0 the same prompt gives the same output — a blind retry is meaningless. The retry prompt contains the schema, the question, **the SQL that failed**, and **the verbatim database error**. The model is asked to fix one specific fault. That is reflection, not resampling.

**Q: Why temperature 0? Don't you want variance for a retry?**
A: Variance is the wrong solution. Raising the temperature and retrying would be betting on "maybe it comes out right this time". Instead I put *new information* into the prompt — the error message. Determinism is also required for SQL (same question, same query) and for a reproducible eval.

**Q: Why `MAX_RETRIES = 3`?**
A: Genuine syntax/schema errors get fixed on the first or second retry once the model sees the error. Anything still failing after three is almost always a semantic failure — the question is not answerable — and raising the limit only burns latency and tokens. It is a cost ceiling. It started as a reasoned choice; the eval harness lets me justify the number by measurement.

**Q: What happens if it still fails after 3 retries?**
A: The `give_up` path goes to the synthesize node, which produces a clean apology — the raw traceback never reaches the user. The error stays in the `logs` array for debugging. Failure is a designed path, not a crash.

**Q: How do you stop the LLM writing DROP TABLE?**
A: It is no longer blocked — it **pauses**. A destructive statement goes to an approval gate: the graph pauses, the exact SQL is shown to the user, and they approve or reject. On reject nothing runs. On approve the statement runs, and `ALLOW_WRITES` decides whether it commits or rolls back. There are layers behind that too — the system prompt, the keyword guard, and the real production answer, a database-level read-only role that prompt injection cannot bypass.

**Q: What was the most interesting thing about implementing HITL?** ← *these two answers set you apart*

A: **Two things I had not anticipated.**

**One — HITL is impossible without a checkpointer.** Pausing and resuming later happens across two separate HTTP requests, so the graph's state has to stay alive in between. Without a checkpointer there is nothing to resume. That is why the stateless path (no `thread_id`) keeps the old hard block — and that is not a gap, it is **the right behaviour**: showing an approval prompt that cannot be honoured is worse than refusing outright. Phase 4 landing before Phase 3 was not a coincidence, it was a precondition.

**Two — the whole phase had become dead code, and the first test caught it.** My system prompt said "only ever write SELECT queries". After building the gate I tested it — "Delete all employees from HR" — and the model wrote a `SELECT`. The gate was skipped. That constraint existed **because** there was no gate; leaving it in after building one means destructive SQL is never generated, the gate never fires, and the feature looks like it "works" while nothing ever reaches it. That prompt line is now conditional on `hitl_enabled`.

> **Say this line:** *"A feature that passes because its code never runs has not been tested. So for every new guard I now ask first whether a path to trigger it actually exists."*

**Q: Does an approved DELETE really run? Isn't that dangerous on a public demo?**
A: That is what `ALLOW_WRITES` is for. At the default `false` an approved statement **still runs** — Postgres plans it, enforces every constraint, reports how many rows it would have touched — and is then rolled back. That makes the gate demonstrable on a public URL without giving any visitor the ability to empty a table.

And it is not approval theatre: the response says plainly that it was rolled back and how many rows would have been affected. **Running in a safe mode and lying are two different things.**

**Q: And what if `ALLOW_WRITES=true`?**
A: Then the synthesis prompt has to change too — and this is where I ran into my own old bug again. The prompt used to hardcode "this system is STRICTLY READ-ONLY". With `ALLOW_WRITES=true` that made it lie in the **opposite** direction: a write that genuinely committed would be reported as "nothing changed". The prompt is now conditional on the flag. Same lesson as the false-confirmation bug, just mirrored — **no false confirmation, and no false reassurance.**

**Q: Is there any auth on the approve endpoint?**
A: No, and I will say that myself. `thread_id` is generated by the client and is unauthenticated — whoever has the thread id can approve a write on that thread. Fine for a single-user demo, not for real use: that needs auth on the approve endpoint and a per-user namespace on the thread key. It is the same limitation as conversation memory, except here the consequence is changing data rather than reading it — so it is more serious.

**Q: Did you find any bug in testing?** ← *this is your best story, be ready for it*
A: Yes, one that taught me a lot. I asked the UI "Delete all employees from HR". Every data-touching layer behaved correctly — the system prompt kept generation to a SELECT, so the keyword guard never even needed to fire, and nothing in the database changed. Then the synthesizer read the question, saw two rows come back, and answered: **"The employees Anjali Nair and Vikram Singh have been removed from the HR department."**

Nothing had been removed. **The guard protected the data, but the narration lied.**

That matters because my whole threat model was looking in the wrong place — every safety layer existed to prevent an *unauthorised write*, and they all worked. But a user told that a deletion happened is harmed either way — they stop looking for records that still exist, or they tell the team the job is done. **A false confirmation is its own class of harm, independent of the action it claims to describe.**

The fix is in the synthesis prompt: tell the model the system is strictly read-only and that it must never imply data was added, changed or removed; on a modification request it should say plainly that it can only read, then describe the result. The answer now comes back as *"I can only read data and cannot perform deletions"* followed by the HR roster.

**The lesson to state:** *"Guarding an action and guarding the report of that action are two different things. And this gap only appeared in an end-to-end UI test — a unit test would never have caught it, because every component was doing its own job correctly."*

**Q: What about SQL injection risk?**
A: Classic injection takes a different shape here — user input is not being concatenated, the LLM generates the whole query. So the risk is not "a malicious string escaped", it is "a prompt made the model write a destructive query". Which is why the defence is layered prompt + keyword + DB role, not parameterization — there is nothing to parameterize, the query itself is the generated artifact.

**Q: Why did you switch from SQLite to Postgres?**
A: SQLite's type affinity is so forgiving that many wrong queries still run — meaning the self-healing loop never gets the errors it exists for. Postgres is strict and returns precise error messages, which is exactly the feedback signal the retry depends on. And production would be Postgres anyway.

**Q: How do you give the schema to the LLM? Live introspection?**
A: Right now it is a hard-coded plain-text description. Deliberately — I can put semantic hints in it (the actual department values) that raw DDL does not carry, and the prompt cost stays fixed. The limitation is that a schema change means updating it by hand, and on a 200-table schema it will not scale — that needs introspection plus retrieving only the relevant tables.

**Q: How would you scale this?**
A: There are three separate bottlenecks. The FastAPI layer is stateless and scales horizontally. The database already has connection pooling (`pool_pre_ping`), with PgBouncer next. The real bottleneck is LLM latency — one self-healing run can be up to 4 generation calls plus synthesis, so I would cache successful question→SQL pairs so repeated questions never hit the LLM.

**Q: How would you test this?**
A: Two levels. Unit — `should_retry` is a pure function, so every routing case tests directly; `_extract_sql` gets tested on fenced, unfenced and noisy inputs. Integration — the eval harness exists: 20 questions with gold SQL, and an accuracy delta measured at `MAX_RETRIES=0` vs `3`. That delta is the project's real metric.

**Q: How do you measure accuracy? Do you match the SQL?** ← *a good question, learn this answer*
A: No — I use **execution accuracy**, the standard Text-to-SQL metric. I run both the gold SQL and the agent's SQL and compare the **result sets**. Not string matching, because one question can have many equally-correct SQL forms — that would measure stylistic agreement, not correctness. And not LLM-as-judge, because that puts the reliability problem inside a component that is itself unmeasured — and measurement was the whole point.

**Q: Why report two metrics (accuracy and strict)?**
A: Because the questions do not specify the projection. "Who is the highest paid employee?" is answered correctly by `SELECT name` and by `SELECT name, salary, role`. Calling the second one wrong measures prompt compliance, not SQL correctness. So the headline metric is relaxed — the gold answer has to be contained in the agent's result, with the same row count — and strict exact-match is reported in its own column. I actually started with strict only, and in the very first smoke test a correct answer FAILED because the agent returned extra columns. That is when the metric changed.

**Q: Your eval shows retries made no difference. So what is the loop for?** ← *the toughest question, and the answer is what sets you apart*

**The real numbers — three conditions, `gemini-3.5-flash-lite`, 20 questions. Only the schema description changed; questions, DB and code stayed the same:**

| Condition | Retries off | Retries on | Delta | Avg retries |
|---|---|---|---|---|
| Production schema (hand-tuned) | 95% | 95% | **+0pp** | 0.00 |
| Degraded schema (bare column list) | 90% | 90% | **+0pp** | 0.00 |
| **Stale schema (wrong column names)** | **15%** | **30%** | **+15pp** | 2.25 |

**The headline to say:** *"The self-healing loop doubles accuracy — but only where queries actually fail."*

A: Correct, and I found that by measuring it myself — which is why I have the full explanation. In the first two conditions **`avg retries = 0.00`**, meaning **the loop never fired once.** Not a single query was rejected by Postgres. So those runs are not measuring the architecture at all, they are measuring the **prompt** — if the mechanism under test never activates, that eval says nothing about it.

So I built a third condition — **stale schema**: column names in the description that no longer exist (`emp_name` where the real column is `name`). That is **schema drift**, the most common breakage in real Text-to-SQL deployments. There the queries genuinely fail, the loop fires, and **accuracy goes from 15% to 30%.**

And how it works is specific too — Postgres does not just say "no such column", it says `HINT: Perhaps you meant to reference the column "employees.name"`. That hint goes into the retry prompt. That is why error-informed regeneration beats blind resampling: the model does not have to guess again, it is handed the correction.

**Why only 30%, honestly:** in the stale condition *every* column name is wrong, and Postgres hints one column at a time — three retries are not enough (`avg retries 2.25`, very close to the ceiling of 3). In real drift one or two columns change, and there the loop recovers far more.

The reason the first condition has a 95% baseline is that my `get_schema_description()` is hand-tuned: it has example values, an explicit relationship line, and a direct warning that `employees` has no department name column so a join is mandatory. With that much guidance the model does not write a wrong query, so the loop never fires. In that condition the eval measures the **prompt**, not the **architecture**.

So I added a second condition — `--degrade-schema`. It replaces the schema description with a bare column listing: no relationship line, no example values, no join warning. That is what a schema description generated by introspection looks like, which is what happens in real deployments — nobody hand-writes hints for a 50-table schema. In that condition the model has to infer the join itself, it makes mistakes, and **then** the loop has something to heal.

Two different questions get answered: the normal schema tells you "what does the loop add on top of a good prompt", the degraded schema tells you "how much accuracy does the loop recover with a realistic prompt". The second is the honest test of the architecture — a loop that only helps on a prompt you have already tuned is not doing much.

**Q: The one question that failed — why didn't a retry save it?** ← *a very strong answer, remember it*
A: The question was "For each department, what percentage of its budget goes to salaries?" The agent wrote:
```sql
SELECT d.name FROM departments d JOIN employees e ON d.id = e.department_id
GROUP BY d.id, d.name ORDER BY SUM(e.salary) ASC LIMIT 1
```
That SQL **is valid and executes cleanly** — it just answers the wrong question (the lowest-spending department, not a percentage). It is a **semantic** failure, not a syntactic one. And my loop structurally cannot catch it, because the loop runs on database exceptions — and here there is no exception. That is exactly the failure class my architecture does not address, and I know it. Catching it needs a different mechanism — an LLM critic validating the result against the question, or self-consistency (generating two queries and comparing results).

**Q: What if the delta had come out small on the degraded schema too?**
A: Then I would say what the data says — at this schema size, with this model, the loop's contribution is X. Two tables and 20 questions do not support a universal claim. The real value shows up when the schema is larger and the ambiguity higher. The point is that I **measured** it and I know my system's limits — a very different position from "I built it, it works".

**Q: How did you handle rate limits?**
A: The free tier gives only **20 requests per day** on some models, and one self-healing run can make up to 5 LLM calls — so a 429 is not exceptional, it is expected. The harness does exponential backoff and retries the whole question; if it still fails after 5 attempts the error is recorded, not silently dropped. And the quota is per model, so the eval runs on the `-lite` model via the `GEMINI_MODEL` env var while the demo runs on the standard one.

**Q: How would you debug the agent taking a wrong step?** ← *the most common production question about agentic AI*
A: There are two layers. The `logs` array is appended by every node and goes out in the API response — that is user-facing explainability, and it shows which node ran and in what order. But it is not enough for debugging, because it does not contain the raw prompt. For that, LangSmith is wired — `LANGCHAIN_TRACING_V2=true` plus a key, and that is all: there is not one line of tracing code in the application, LangChain's callback system instruments every LLM call itself. There the whole retry chain is a nested trace — every `generate_sql` invocation, its exact rendered prompt with the injected error, the raw response before `_extract_sql`, latency, and per-attempt token cost.

**Q: What does that tell you in practice?**
A: Three things that used to be guesswork. One — **whether the retry is actually working**: the trace shows whether attempt 2 incorporated the error or just wrote the same query again. That is this project's core mechanism, so being able to verify it matters. Two — **prompt regression**: if editing the schema description degrades generation, the diff is visible in the traced prompt. Three — **cost attribution**: how expensive a retry is in tokens, and which node is heavy in a slow request. Together with the eval harness, those three numbers turn the retry budget from a reasoned choice into a measured one.

**Q: Is that tracing on for everyone?**
A: No, it is opt-in — `false` by default in both `.env.example` and `docker-compose.yml`. Anyone forking the repo should be able to run it without a LangSmith account, and with tracing off there is zero overhead because no code path depends on it. And it is deliberately server-side — raw prompts should not reach the client, which is why they are never put in the `logs` array.

**Q: How would you deploy it?**
A: Postgres on Neon (serverless free tier), the FastAPI Docker image on Render, secrets injected as env vars. Render's free tier cold-starts, so I warm the URL before a demo — and an UptimeRobot ping every 10 minutes keeps it from sleeping at all.

### Credibility — the hardest questions, and they will come

These three questions are parts of one attack. **Dodging them is the biggest risk.**
The strongest answer is to **agree with the interviewer**, then show what is left
after that.

**Q: Any AI agent can build this. What is yours in it?**

A: **Don't fight this — concede it.**

> "Completely fair. The scaffold takes an hour. But two things AI does not do on its
> own — **finding out whether the system actually works**, and **saying so honestly
> when it doesn't**. Let me show you my eval."

Then open this number:

| Condition | Retries off | Retries on | Delta |
|---|---|---|---|
| Production schema | 95% | 95% | **+0pp** |

> "My core feature — the self-healing loop — **contributed nothing**. `avg retries =
> 0.00`, meaning it never fired. With a good schema description the model does not
> write a wrong query. So that eval was measuring my **prompt**, not my
> architecture.
>
> An AI-generated project **never shows that number** — it shows a flattering one. I
> measured this, understood it, and published it. Then I built a third condition
> where the loop does fire, and there accuracy went from 15% to 30%."

**This is your strongest 60 seconds.** Learn it with the numbers.

**Q: You must have used AI to build this too.**

A: Do not lie — you will be caught, and then every other claim is in doubt.

> "Yes, I had AI write code. Everyone does now. The question is not who typed it —
> the question is which **decisions** were made and whether they can be defended. I
> can tell you about four bugs that AI did not catch and I did."

And then these four — **learn them, they are your real proof:**

**1. The guard saved the data, the narration lied.**
Asked "Delete all employees from HR". Every safety layer worked, nothing changed.
But the answer came back: *"The employees Anjali Nair and Vikram Singh have been
removed."* Nothing had been removed.
→ *"Guarding an action and guarding its **report** are two separate
responsibilities. This only showed up in an end-to-end UI test — every component was
doing its own job correctly."*

**2. A whole feature was dead code.**
Built the HITL gate, tested it — the model wrote a `SELECT` and the gate was
skipped. The system prompt said "only ever write SELECT", a constraint that existed
**because** there was no gate.
→ *"A feature that passes because its code never runs has not been tested."*

**3. A chart was lying about the data.**
The dashboard gave "average salary by department" a donut. A donut says "these are
parts of a whole" — but averages do not add up.
→ *"Fix: donuts only for additive measures. When the guess is wrong you get a bar,
which is always honest."*

**4. Phase 4 had to come before Phase 3.**
HITL needs a LangGraph interrupt, and an interrupt is impossible without a
checkpointer — pause and resume are two separate HTTP requests.
→ *"That was not a coincidence, it was a precondition."*

**Q: This is dummy data. Why not a real dataset — Kaggle, Hugging Face?**

A: This answer is **strong, not defensive.** Three reasons, in this order:

> "The data is synthetic, and deliberately so.
>
> **One — my eval depends on it.** The seed is fixed (`random.Random(42)`), so every
> machine produces exactly the same 160 rows. That is what makes numbers like 95% /
> 90% / 15%→30% comparable between runs. If the data changed each time, the claim
> 'self-healing improved accuracy' would be meaningless, because you could not tell
> whether accuracy rose because of the loop or because the data got easier.
>
> **Two — the schema was designed for the agent.** I deliberately left the department
> name out of `employees` so the model has to **infer** the join. Salary bands are
> tied to roles and manager roles go to only 10% of people, so that 'average salary'
> and 'highest paid' give different answers — with flat random both would be pure
> coincidence.
>
> **Three — most public HR datasets are a flat CSV.** Importing one would put me
> straight back where I started: a single table, no join, and no errors at all for
> the self-healing loop. That is a downgrade, not an upgrade."

**And then go further yourself — this is what completes the answer:**

> "But there is a real weakness, and it is not the data, it is **the schema**: three
> tables is still small. The hard part of real Text-to-SQL is 30-50 tables and
> ambiguity, where the schema description does not fit in the prompt and you need
> schema retrieval. The next step is not Kaggle — it is **Spider**, the academic
> Text-to-SQL benchmark, whose gold queries are already labelled. That would test
> whether the loop still holds up on a schema an order of magnitude larger."

> **Why that line works:** you are not just naming your limit — you are saying **how
> you would test it**, and which tool is the right one for that.

**Q: What is the need for this? It isn't a real product.**

A: Do not over-sell.

> "This is a portfolio project, not a product — and I am not claiming otherwise. But
> the failure it addresses is real: in an internal BI copilot the user cannot debug a
> SQL error. They need either an answer or a clear 'not found' — not a stack trace. I
> picked that one failure mode, built a whole system around it, measured it, and
> wrote down its limits."

### The one line that closes every credibility question

> "You can ask me **why** about any part of this project — why the retry limit is 3,
> why I dropped SQLite, why a bar and not a donut, why MCP is off by default, why the
> approve endpoint returns 409 and not 200. There is an answer for every one, and a
> trade-off I chose in each."

That is the thing an AI-generated project **does not have** — it has code, not
decisions.

### What NOT to say to this question

| ❌ Wrong | Why |
|---|---|
| "I wrote all of it myself" | You will be caught, and then every other claim is in doubt |
| "AI couldn't build this" | It could. Do not fight it — concede and move on |
| "This is production-ready" | It is not, and your own docs say so |
| Getting defensive | The question is fair. Agreeing and moving forward is the win |

---

### Product / Business

**Q: Where would this actually be used?**
A: Any internal analytics/BI copilot where non-technical people ask questions of data. Self-healing matters there because the user cannot debug a SQL error — they need an answer or a clear "not found", not a stack trace.

**Q: How would you measure that it is working?**
A: Three metrics. Execution success rate (what % of questions produced valid SQL), answer accuracy (against expected answers on a fixed question set), and average retries per question. The most important number: the difference in accuracy with retries versus without — that is the entire business case for this architecture.

**Q: What about latency? A retry makes it slower.**
A: It does — worst case 5 LLM calls. But compare against the baseline: without a retry that query *fails* and the user has to retype it, or gives up. Spending an extra second to get the right answer automatically beats returning an error instantly. And on the happy path there is zero extra cost — the retry only fires on failure.

---

## 11. Positioning Alongside My Other Projects

Present the three projects as one **pattern**, not as three separate projects:

> **"Agentic Self-Correcting Systems"** — three projects, one architectural idea (LLM + self-verification + autonomous correction), three different failure domains and three different graph topologies.

| Project | What it fixes | Graph topology | Correction signal |
|---|---|---|---|
| **Self-Healing SQL Agent** | SQL *execution errors* | **Cycle** — a retry edge back to generation | The database's exception (deterministic, ground truth) |
| **Adaptive CRAG** | Retrieval *relevance* | **Branch** — conditional fallback to web search | An LLM grader's judgement (probabilistic) |
| **Code Guardian** | Code *defects* | **Tool-calling supervisor** — the LLM decides which specialists to run | Specialist agents' findings, synthesized into a patch |

**One more difference worth stating separately** — *who* decides the control flow:

- In the SQL Agent and CRAG, **LangGraph's edges** decide the next node (`should_retry`, the grading branch). That is deterministic and auditable.
- In Code Guardian, **the LLM itself** decides, via `bind_tools` — it emits a tool call and the graph executes it.

> "Both patterns are deliberate. In the SQL agent the control flow *should* be deterministic — the retry decision comes from a database error, not from a model's judgement, and putting an LLM in there would turn a reliable signal into a probabilistic one. In Code Guardian the model's judgement *is* the routing signal — which audit is needed can only be known by reading the code. The real skill is knowing when to use which."

**If asked "do these overlap?":**
> "They share a pattern, not an implementation. The graph topology is different in all three — a *cycle* in the SQL agent, a *conditional branch* in CRAG, a *fan-out supervisor* in Code Guardian. The correction signal differs too: the SQL agent gets deterministic ground truth from the database, CRAG gets an LLM grader's probabilistic judgement — which is why CRAG needs guardrails more, while the SQL agent's feedback is reliable on its own. Together they show that I can build all three canonical shapes of agentic control flow."

That answer is very strong — it turns a portfolio into a coherent *skill story*.

---

## 12. Demo Strategy

The interviewer should **see self-healing happen**, not just a chat box.

### Scenario 1 — Happy Path
"Who earns more than 80000 in Engineering?" (this is a join now too — Engineering lives on `departments`)
Flow: `generate_sql` → `execute_sql` (success) → `synthesize`. `retry_count: 0`.
**Talking point:** "A simple case, zero retries — self-healing only fires when needed, it is not overhead on every query."

### Scenario 2 — The Correction Path (the real USP)
With the FK schema this now triggers naturally. Ask something that forces a join and tempts the model into a flat-table assumption — "Which department has the highest average salary?" or "Who works in Bangalore?". If the model assumes `employees.department` or `e.location` (neither of which exists), Postgres returns the exact error — `column e.department does not exist` — and that error goes into the retry prompt.
Flow: `generate_sql` → `execute_sql` **fails** → `column "..." does not exist` in the logs → `Retry 1` → corrected SQL → success.
**Talking point:** "The agent read the error itself, understood what was wrong, and fixed the query — I said nothing. That is not a retry, it is a repair."

### Scenario 3 — Guard Catch
"Delete all employees from HR."
Flow: the gate pauses, showing the exact statement.
**Talking point:** "This never reaches the database without a human decision. And I do not retry it — it is a policy rejection, not an error."

### What to highlight in the UI
- **The `retry_count` badge** — the difference between 0 and 1 is the whole story
- **The execution trace / step logs** — the most impressive part
- **The generated SQL** — show that it is not a black box

### Practical tips
- Keep fixed demo questions that predictably trigger a retry — do not rely on live randomness.
- Keep a screenshot of the trace logs for the portfolio.
- Render's free tier cold-starts — warm the URL 5 minutes before a demo.

---

## 13. One-Liner for Resume/LinkedIn

> "Built a Self-Healing Text-to-SQL agent using LangGraph's cyclic state machine — it feeds verbatim PostgreSQL execution errors back into the LLM to autonomously repair failed queries (up to 3 attempts), with read-only enforcement and a full node-by-node execution trace exposed via FastAPI."

---

## 14. Quick Reference — AgentState Schema

```python
class AgentState(TypedDict):
    question: str       # Original natural language question
    sql_query: str      # Most recently generated SQL statement
    query_result: str   # Raw database output (stringified rows)
    error: str          # Exception message; "" means success
    retry_count: int    # Current retry iteration (ceiling: MAX_RETRIES = 3)
    final_answer: str   # Validated natural language response
    logs: List[str]     # Step-by-step trace logs for UI visibility
```

Routing:
```python
def should_retry(state) -> str:
    if state["error"] and state["retry_count"] < MAX_RETRIES: return "retry"
    if state["error"]:                                        return "give_up"
    return "success"
```

---

## 15. Honesty Checklist — What NOT to Claim

Overclaiming is the biggest risk in an interview. If the interviewer opens the code and a claim turns out to be false, the whole project's credibility goes. **Keep these straight:**

| ❌ Don't say | ✅ Say |
|---|---|
| "It validates output with Guardrails AI" | "Guardrails AI could not be used — a hard dependency conflict in both directions. I built a deterministic validator instead, which is a better fit because schema leakage is syntactic" |
| "It handles large production schemas" | "There are three tables with FKs, so join reasoning gets tested — but on a 50-table schema the description will not fit in the prompt and you need schema retrieval. This proves join *reasoning*, not schema *scale*" |
| "Accuracy is X%" — **without naming the condition** | Always name the condition. 95% is the production schema, 15%→30% is the stale schema |
| "It's production ready" | "It's a portfolio project; production needs a read-only DB role, CORS tightening, and auth" |
| "Self-healing doubled accuracy" — **without the condition** | The number is true (15% → 30%) but it is from the **stale-schema** condition. On the production schema the delta is **0%**. Always say it with the condition: *"where queries actually fail the loop doubles accuracy; where the prompt is good the loop never fires and contributes zero. I measured both."* Saying the number without context is cherry-picking, and the interviewer can open results.json |
| "I analyse traces in LangSmith" — **if you have never opened the dashboard** | Tracing is wired, but **before an interview set `LANGCHAIN_TRACING_V2=true`, run a deliberately failing query, and look at the retry chain in LangSmith yourself.** Take a screenshot. Otherwise "what does it look like?" gets asked and there is no answer — wiring something up and reading a trace are two different claims |
| "The `ALLOW_WRITES=true` commit path is tested end to end" | It is covered by unit tests only. It was never run against the real database, because it would genuinely delete rows |
| "It integrates with Power BI" | It is an **export** — a `.pbids` file and Power Query scripts. A service integration needs an Azure AD app registration and tenant permissions this project does not have |
| "It works with any MCP server" | The MCP client is generic, but it has only ever talked to **our own** server. The protocol is demonstrated, a third-party integration is not |

**Why this matters:** "I didn't build that, and I know why it matters" is *more* impressive than a false "I built everything". Interviewers look for gaps — telling them yourself keeps you in control.

---

## 16. How strong this project is — an honest assessment

This section is for you, not for the interviewer. Reading it should tell you **what
position you are speaking from**.

### Its strength is not the feature list

LangGraph + MCP + HITL + memory + eval — all of that **looks** impressive, but a good
interviewer works out within 10 minutes that a feature list can be produced by AI.
Do not play on that field.

**The real strength is three things:**

**1. You measured your own system and published a negative result.**
That is the rarest thing here. Most candidates never measure; those who do only show
the good number. You have it written down that the core feature contributed +0%, why
it did, and that you then built a condition where it genuinely fires. **That signal
cannot be faked.**

**2. Four bugs that only come from thinking.**
False confirmation · a dead-code feature · the donut's lie · Phase 4 having to come
before Phase 3. Not one of those comes from codegen. They come from someone asking
*"is this actually working, or is it just passing?"*

**3. Every decision is written down with its cost.**
"MCP is off by default because it is slower and its benefit is swappability, not
speed." "409 not 200, because otherwise the user believes their decision was
applied." That is trade-off language, not feature language.

### Weaknesses — you need to know these

| Weakness | How big |
|---|---|
| **Three tables, 160 rows** | Big. Real Text-to-SQL pain is 50 tables and ambiguity — this schema is still small |
| **Not deployed** | **The biggest.** Without a link, a portfolio project loses half its value |
| 20 questions, one model, one schema | The eval gives direction, not statistical proof |
| No auth anywhere | Both `thread_id` and the approve endpoint are unauthenticated |
| Single user | In-memory rate limiter, one container, no answer for concurrency |
| MCP only talks to our own server | The protocol is demonstrated, a third-party integration is not |

**All of these are already written in the docs — and that is what protects you.**
An interviewer stops hunting once a candidate names their own limits.

### Which level this fits

| Level | Verdict |
|---|---|
| **Fresher / 0–2 years** | **Well above** the bar. Most people do not have this |
| **2–4 years (mid)** | **Strong and competitive** — this is the target zone |
| **Senior (5+)** | The project alone is not enough — that needs production scale, load, on-call. But the **thinking** is senior-level; the gap is scale, not thinking |

### The biggest irony of this project

**Its core feature came out weak in its own eval** — with a good prompt the
self-healing loop never fires.

Most people would hide that. You published it. **And that is what makes this project
interview-worthy**, because you can now answer a question very few people can:
*"how do you know your agent is working?"*

### Priorities now — and no new features are among them

1. **Deploy it** (~40 min) — the highest-value thing left, more than any new feature
2. **Learn the eval story** — 60 seconds, with the numbers. That is the differentiator
3. **Keep a live demo ready** — the stale-schema case, where the retry is genuinely visible
4. **Look at one LangSmith trace yourself** — 5 minutes, and the claim becomes yours

> **Do not build more features.** There are already more than enough. What is left is
> **presentation**, not code.
