# Build Plan — how this was actually built

[ROADMAP.md](ROADMAP.md) is what exists. [PROJECT_WALKTHROUGH.md](PROJECT_WALKTHROUGH.md)
is how the system works. This file is the *process*: the order things were built
in, the rule that decided that order, and — the part worth reading — where the
time actually went versus where it was expected to go.

It is here because "how do you work?" is a real interview question, and the
honest answer is more interesting than a tidy one.

---

## The rule that set the order

**Build the thing that can be measured, then measure it, then decide what to
build next.**

Not "build all the features, then evaluate at the end". The evaluation harness
landed early, immediately after the core loop, and it changed the plan twice:

- It produced **+0pp** on the production schema, which killed the assumption that
  the retry loop was carrying the project. The response was not to hide the
  number but to design a third condition where the loop genuinely fires.
- It forced `MAX_RETRIES` to become runtime-patchable rather than a constant,
  which is why `config.py` exists as its own module.

A feature you cannot measure is a feature you cannot defend.

---

## Order of execution

| # | Built | Why here |
|---|---|---|
| 1 | Postgres + seed data + `run_sql` | Nothing can be tested without a database that answers questions |
| 2 | The LangGraph loop — generate → execute → retry | The actual claim of the project |
| 3 | FastAPI endpoint | Needed to exercise the loop from outside |
| 4 | **Eval harness** | Earliest point where the claim could be checked |
| 5 | React UI + agent-trace rail | The retry count has to be *visible*, or the demo is a black box |
| 6 | Output validation | Small, deterministic, and it closes the "what if it leaks the schema" question |
| 7 | MCP transport | Turns data access into a swappable interface |
| 8 | Postgres checkpointer (memory) | Had to precede HITL — an interrupt needs somewhere to save state |
| 9 | HITL approval gate | Only possible once (8) existed |
| 10 | Bigger seed data (160 employees, 3 tables, dates) | 10 rows made the dashboard look empty and made multi-hop joins impossible |
| 11 | Generated dashboards → Power BI export | Each widget is a full agent run, so this reuses everything above |
| 12 | Saved conversations | Fixed a real bug (see below), did not add a feature |
| 13 | UI rebuild, rename, PG 18, status bar | Presentation — last, on purpose |

**Phase 4 before Phase 3 is the one inversion worth pointing at.** The roadmap
numbered HITL before memory. Reality reversed it: LangGraph's `interrupt_before`
needs a checkpointer, so the approval gate could not exist until conversation
state was durable. Noticing that mid-build, rather than shipping a gate that
silently never fired, is the kind of thing the ordering rule is for.

---

## Where the time actually went

Plan versus reality. The estimates were not badly wrong about the *features* —
they were wrong about which parts would fight back.

### Roughly as expected

- **The LangGraph loop itself.** The cyclic graph, conditional edges and retry
  prompt came together close to the estimate. The framework does this well.
- **FastAPI + Docker Compose.** Routine.
- **The output validator.** A few regexes and a decision about what *not* to
  enforce. Half a day.

### The real time sinks

**1. Dependency walls — twice, on the same package.**
`guardrails-ai<=0.5` wants `langchain-core<0.3`; `>=0.6` wants `>=1.0`; this
project is on langgraph 0.2 / langchain 0.3, which needs `<0.4`. There is no
version in between. Using it meant a full langchain 1.x migration — breaking the
checkpointer and graph APIs — for one validator. The second attempt burned time
re-confirming the first. Outcome: a deterministic guard, which turned out to be
the better design anyway.

**2. Model ids getting retired mid-project.** `gemini-2.0-flash` and
`gemini-2.5-flash` both disappeared while this was being built. That is why
`GEMINI_MODEL` is an environment variable — a hard-coded model name is a time
bomb in any LLM app. It also cost a cycle of "why is everything 404ing".

**3. MCP broke FastAPI.** Adding the `mcp` package let the app *import* fine and
then die at request time with `Router.__init__() got an unexpected keyword
argument 'on_startup'`. The fix was upgrading fastapi 0.115 → 0.141, which in
turn deprecated `@app.on_event("startup")` and forced the move to `lifespan`. One
dependency, three files changed.

**4. MCP 2.x renamed `FastMCP` to `MCPServer`.** First run failed. The fallback
behaved exactly as designed — logged the reason, used the direct driver — which
was the first evidence the fail-open path was worth building.

**5. Free-tier quota.** Some models allow 20 requests a *day*. A full eval sweep
is 40+ calls. Exponential backoff had to be added to the harness before the
numbers could be collected at all.

**6. A bug that looked like a UI problem and was not.** "Everything disappears on
refresh" was really: the UI generated a fresh `thread_id` on every page load, so
every past conversation stayed in Postgres and became *unreachable*. Nothing was
being deleted — it was being orphaned. Fixing it produced
`app/conversations.py`, and its first version was also wrong (it tried to read
`checkpoint_blobs` with SQL; LangGraph stores those as msgpack, not jsonb).

**7. PostgreSQL 18's mount point moved.** PG 18 expects
`/var/lib/postgresql`, not `/var/lib/postgresql/data`. The container simply
refused to start against the old volume.

### Bugs worth keeping on the record

Each of these produced either a test or a design change:

| Bug | What it really was | What it left behind |
|---|---|---|
| The guard blocked a write, but the answer said rows *"have been removed"* | The synthesizer narrating an action that never happened | The rejection answer is now a fixed string, never model-generated — and a test asserts no LLM call happens on that path |
| HITL was dead code | The system prompt forbade non-`SELECT`, so the gate could never fire | The prompt is now conditional on `hitl_enabled` |
| A donut chart for "average salary by department" | A donut claims "parts of a whole"; averages do not add up | `_is_part_of_whole()`, and a test named after the bug |
| Strict-only eval metric failed a *correct* answer | The agent returned extra columns | A relaxed "contains" metric alongside strict, with both reported |
| KPI text spilling out of its tile | An inner `div` with no display, so spans flowed inline | A flex column with `min-width: 0` |

---

## What is left, and it is not code

Everything below needs an account or an hour of attention — none of it needs a
commit.

| | |
|---|---|
| ⬜ **Deploy** | Neon + Render + UptimeRobot. ~40 minutes, checklisted in [DEPLOYMENT.md](DEPLOYMENT.md). The single biggest gap. |
| ⬜ **Look at one LangSmith trace** | Wired but never observed. Run the stale-schema eval with tracing on and open a retry chain. You cannot defend an observability claim you have not seen. |
| ⬜ **Rehearse the eval story** | 95% / 95% / **+0pp**, then stale schema 15% → 30%. Sixty seconds, out loud. It is the strongest card in the deck and the easiest to fumble. |

---

## How this was built

The code was written with heavy use of an AI coding assistant (Claude), working
through the order above, with each stage run against a real Postgres and a real
model before moving on.

What that did **not** decide: that the evaluation had to come before the features,
that a `+0pp` result had to be published rather than buried, that a third condition
was needed to make the loop actually fire, that the write gate and the retry edge
must stay deterministic rather than become the model's opinion, and that a
synthesizer which narrated a deletion that never happened was a bug worth a
prominent write-up.

Those judgements, and the measurements behind them, are the project. They are in
[CODE_QA.md](CODE_QA.md) and [eval/RESULTS.md](../eval/RESULTS.md).

---

## How to read the rest

| | |
|---|---|
| [PROJECT_WALKTHROUGH.md](PROJECT_WALKTHROUGH.md) | Start here — the flowchart and the build story in detail |
| [ROADMAP.md](ROADMAP.md) | What exists, what does not, what is next |
| [CODE_QA.md](CODE_QA.md) | Defending the code line by line |
| [SETUP.md](SETUP.md) | Running it, and the errors listed above with their fixes |
