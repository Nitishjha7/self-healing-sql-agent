# Roadmap — what is built, what is not, and what is worth doing next

The README states the headline and the limits. This file is the honest ledger
behind it: every phase, what it actually delivered, and **what it did not** —
because a phase marked "done" with nothing said about its edges is the kind of
claim that falls apart in the first follow-up question.

Ordering rule used throughout: *measurement before features.* A thing that tells
you whether the architecture works ranks above another thing the architecture
can do.

---

## Current status

| | |
|---|---|
| ✅ | Self-healing retry loop — LangGraph `StateGraph`, conditional edges, the database error fed back into the prompt |
| ✅ | Evaluation harness — 20 questions with gold SQL, execution accuracy, three schema conditions, retries on vs off |
| ✅ | Human-in-the-loop approval — `interrupt_before`, `ALLOW_WRITES` decides commit vs run-and-roll-back |
| ✅ | Conversation memory — `PostgresSaver` keyed by `thread_id`, survives a restart, fails open to stateless |
| ✅ | Output validation — deterministic guard, reported through `guardrail_flags` |
| ✅ | MCP transport — `USE_MCP=true` routes database access through an MCP server over stdio |
| ✅ | AI-generated dashboards — one sentence → several self-healed queries, widget picked from result shape |
| ✅ | Power BI export — `.pbids` + Power Query (M), DirectQuery, no credentials in the file |
| ✅ | Saved conversations — the thread id survives a reload; the sidebar lists, reopens and deletes |
| ✅ | React + Vite UI — chat, live agent-trace rail, dashboards, schema explorer, live status bar |
| ✅ | Test suite — 69 tests, no API key and no database needed |
| ✅ | Deployment-ready — single-service image, per-IP rate limiting, `render.yaml` |
| ⬜ | **Actually deployed** — no live URL yet |
| ⬜ | **Authentication** — `thread_id` and `/api/approve` are unauthenticated |

---

## The phases, and what each one left open

### Phase 1 — the self-healing loop ✅

A cyclic `StateGraph`: `generate_sql → execute_sql → (error? → generate_sql)`,
capped by `MAX_RETRIES`. The retry prompt carries the failed SQL **and** the
Postgres error text, so attempt two is informed rather than a re-roll.

**Still open:** the loop only sees *execution* errors. SQL that is valid but
answers the wrong question — a semantic failure — passes straight through, and
nothing in this architecture catches it. That limit is the reason Phase 7 exists.

### Phase 2 — Model Context Protocol ✅

`app/data_access.py` picks the transport; the graph never learns which one ran.
The hard part was not the protocol but the sync↔async bridge — see
[CODE_QA.md](CODE_QA.md) for why a background thread with its own event loop beat
the two obvious alternatives.

**Still open:** this talks to *our own* MCP server. The point of a standard
protocol is that the same agent could be pointed at a third-party one without
changing — that has not been demonstrated, and claiming it would be a stretch.

### Phase 3 — human-in-the-loop approval ✅

A modifying statement pauses the graph instead of being refused. The user sees
the exact statement and decides.

**Still open:** `/api/approve` is unauthenticated, exactly like `thread_id`.
Anyone holding a thread id can approve a write on it. Fine for a single-user
demo, not for anything more — which is why `ALLOW_WRITES` defaults to off.

**A note on ordering:** this landed *after* Phase 4, not before, and not by
accident. An interrupt needs somewhere to save state, so the approval gate could
not exist until the checkpointer did. Without a `thread_id` the agent still takes
the old hard-block path.

### Phase 4 — Postgres checkpointer ✅

Per-`thread_id` conversation memory, durable across a restart.

**Still open:** isolation is per *thread*, not per *user*. A real multi-tenant
system needs a namespace per user so one tenant's threads cannot be enumerated or
resumed by another.

### Phase 5 — AI-generated dashboards ✅

"Create a dashboard showing X" is split into sub-questions, each of which runs
through the **same** agent — retry loop, output guard and approval gate all
included. The widget type is chosen from the *shape* of the result, not by
another model call, because that part is a rule rather than a judgement.

**Still open:** the plan is one shot. If a sub-question comes back useless, the
planner cannot notice and ask a better one.

### Phase 6 — Power BI export ✅

A generated dashboard exports as a `.pbids` connection file plus one Power Query
(M) script per widget, carrying the agent's SQL in DirectQuery mode.

**Deliberately an export, not an integration.** Publishing to a workspace needs
an Azure AD app registration and tenant permissions this project does not have,
and a button implying otherwise would be a lie. The export says so in its own
`note` field.

---

## What is next, in priority order

### 1. Deploy it ⬜

The single largest gap, and the cheapest to close. Code, image and guide are all
ready — what is missing is an afternoon of account setup: Neon for Postgres,
Render for the service, UptimeRobot so the free tier does not sleep and hand a
recruiter a blank screen. Steps are checklisted at the top of
[DEPLOYMENT.md](DEPLOYMENT.md).

A portfolio project with no live URL is asking the reader to take the README's
word for it.

### 2. Evaluate on Spider ⬜

**This ranks above every remaining feature**, because it is a measurement rather
than a feature.

The honest limit of this project is schema *scale*, not data realism. Three
tables is small, and a hand-written schema description stops being possible
somewhere around thirty. [Spider](https://yale-lily.github.io/spider) is the
standard Text-to-SQL benchmark and ships labelled gold queries, so it answers the
one question this eval cannot: **does an error-informed retry loop still help on
a schema an order of magnitude larger, or does the model start failing
*semantically* — valid SQL, wrong question — where the loop is blind?**

Either answer is worth having. A negative result here would be as useful as the
+0pp result already published.

### 3. Authentication ⬜

Deliberately deferred, not forgotten. Today the `thread_id` *is* the credential:
hold one and you can read that conversation or approve a write on it. The honest
mitigation right now is that `ALLOW_WRITES` defaults to off, so an approved
statement rolls back.

Doing it properly means sessions, per-user thread namespacing (see Phase 4) and a
real decision about who may approve a write — which is a bigger design question
than it first looks, and worth saying so rather than bolting on a login form.

### 4. Semantic evaluation ⬜

The eval scores *execution accuracy*: do the returned rows match the gold query's
rows. That catches wrong SQL. It does not catch SQL that runs, returns rows, and
answers a different question than the one asked — and neither does the retry
loop. Measuring that needs either human labels or an LLM judge, and an LLM judge
needs its own validation before its numbers mean anything.

### 5. Schema scale ⬜

`get_schema_description()` is hand-written. That is the right call at three
tables — it carries example values and states outright that a join is mandatory,
which introspection cannot give you — and the wrong call at thirty. Beyond that
size the field becomes schema *retrieval*: select the relevant subset of tables
per question, then describe only those.

---

## Explicitly not planned

Saying no is part of a roadmap.

- **Fine-tuning a SQL model.** The failure this project addresses is schema
  drift, and a fine-tuned model goes stale against a changing schema exactly like
  a hand-written prompt does. It would cost a lot and move the wrong number.
- **Publishing to the Power BI service.** Needs tenant permissions this project
  does not have. See Phase 6.
- **A second LLM to check the first.** The output guard is deterministic on
  purpose. Schema leakage is a syntactic property — that is a regex's job, and
  adding a model would turn a guaranteed check into a probabilistic one, with
  nothing checking *that* model.
- **Swapping Postgres for something else.** It is doing three jobs here (the
  data, the checkpointer, the conversation list) and doing them for free.

---

## Related

| | |
|---|---|
| [PROJECT_WALKTHROUGH.md](PROJECT_WALKTHROUGH.md) | How it was built, step by step |
| [BUILD_PLAN.md](BUILD_PLAN.md) | How the build was actually run, and where the time went |
| [eval/RESULTS.md](../eval/RESULTS.md) | The measured numbers behind the claims above |
| [INTERVIEW_NOTES.md](INTERVIEW_NOTES.md) | Trade-offs and anticipated questions |
