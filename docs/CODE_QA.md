# Code Q&A — defending this code line by line

[INTERVIEW_NOTES.md](INTERVIEW_NOTES.md) covers the pitch and the architectural
trade-offs. This file is narrower and harder: **questions about specific lines**,
the kind asked by someone who has opened the repo and is looking for the spot
where the story breaks.

Every answer below is checkable against the code. Where the honest answer is "you
are right, and here is why I did it anyway", it says that.

---

## 1. `nodes.py` / `graph.py` — the retry loop

### Q1. `should_retry` is four lines. Where is the actual self-healing?

Not here — this function only routes. The self-healing is in `generate_sql`,
which on a retry receives the failed SQL **and** the Postgres error text in its
prompt. That is the whole mechanism: attempt two is *informed*, not a re-roll.

Keeping the routing this thin is the point. A conditional edge should answer one
question — where next — and the moment it starts deciding *how* to fix things,
the graph stops being readable as a state machine.

### Q2. Then why a graph at all? A `while` loop with a try/except does this.

Fair, and for this size it would. Three things make the graph worth it:

- **The trace is free.** Every node appends to `logs`, and the UI rail renders
  them. With a `while` loop I would have hand-rolled the same thing.
- **The interrupt.** `interrupt_before=["await_approval"]` pauses mid-execution
  and resumes across two HTTP requests. That is not a loop feature — it needs
  durable state and a graph that knows where it stopped.
- **Adding a node is a wiring change.** `graph.py` is 170 lines of pure
  structure; prompts live in `nodes.py`. They change for different reasons, and
  for a long time both meant editing the same 646-line file.

If the answer were only "it retries", the loop would be the honest choice.

### Q3. `is_destructive` is a substring match. `"SELECT * FROM logs WHERE msg = 'updated'"` triggers it. That is a bug.

It is a false positive, and it is deliberate — there is a test named
`test_conservative_about_words_inside_literals` that exists specifically to stop
someone "fixing" it without understanding the trade-off.

The asymmetry decides it: a false positive costs **one unnecessary approval
prompt**. A false negative **changes data nobody agreed to change**. When the two
error costs are that unequal, you tune towards the cheap one.

The honest addition: the real production answer is a database-level read-only
role, which cannot be bypassed by prompt injection at all. This guard does not
replace that, and the docstring says so.

### Q4. A blocked write sets `retry_count = MAX_RETRIES`. Why hack the counter instead of routing properly?

Because the alternative is worse. `should_retry` sends anything with an `error`
back to `generate_sql` while retries remain. A policy rejection is not a fixable
error — the model will write the same `DELETE` again, burn three LLM calls, and
end in the same place.

Forcing the counter exits the loop immediately. It is a blunt instrument and a
dedicated `blocked` route would be cleaner; it is on the list. A test pins the
behaviour with the reason in its assertion message, so the shortcut cannot rot
silently.

### Q5. The rejection answer is a hard-coded string. Why not let the model write it?

This one came from a real bug. An earlier version had the guard correctly block a
write while the synthesizer cheerfully reported that rows *"have been removed
from the HR department"*. The data was safe; the answer was a lie.

A rejection is a **fixed policy outcome**, not something to generate. Letting the
model narrate it gives it room to narrate its way into saying something else.
`test_rejection_answer_is_not_generated_by_the_llm` replaces `_llm` with a
function that raises, so the test fails if anyone reintroduces a call on that
path.

### Q6. Why does `generate_sql`'s system prompt change depending on `hitl_enabled`?

Because without that, the approval gate was **dead code**.

The original prompt said "only ever write SELECT queries" — a rule that existed
precisely *because* there was no gate. Leaving it in meant destructive SQL was
never generated, the gate never fired, and the feature demoed as working only
because nothing ever reached it.

Now the model may write a modifying statement **only on the gated path**, where a
human sees every one of them first. On the stateless path the old hard block
stays, because offering an approval prompt that cannot be honoured is worse than
refusing outright.

---

## 2. `state.py` — state design

### Q7. Why is there no reducer on `history`? Every LangGraph example uses `Annotated[..., operator.add]`.

Because every node here returns `{**state, ...}` — the whole state, including the
full history. An additive reducer would re-append that history at **every node**,
so a single turn through four nodes would grow the list exponentially.

With overwrite semantics, exactly one place appends exactly one turn:
`_append_turn`, called from `synthesize_and_validate`. One writer, one append.
The reducer pattern is right when nodes return *deltas*; these return full state.

### Q8. `run_agent` resets nine fields by hand on every call. That looks like something you forgot to automate.

It is the single most important line of the memory feature, and automating it
would hide it.

LangGraph **merges** the input dict over the checkpointed state. Any key *not* in
that dict carries over from the previous turn. So if `retry_count` were omitted,
a turn that spent 3 retries would push the *next* question straight to
`give_up` — self-healing dies silently — and the trace would show the previous
question's steps.

`history` is the one field deliberately left out, because it is the one that
should carry. That single decision is the difference between a memory feature and
a memory bug, and `TestPerTurnReset` asserts it by reading the source of
`run_agent` and checking each field name appears.

### Q9. Why is `approval_status` per-turn rather than per-conversation?

Because one turn's approval must not authorise the next turn's write. That would
be the same class of bug as carrying `retry_count` forward, except the
consequence is changed data rather than a wrong trace.

### Q10. `_serializable` converts `Decimal` to `float`. You just lost precision on money.

Correct, and worth stating rather than hiding. `Decimal` does not serialize to
JSON, and these rows go into both the API response and the checkpointer — an
unhandled type breaks the API and conversation memory at the same time.

For a salary figure rendered in a table, float is fine. For a system doing
financial arithmetic it would not be, and the right fix is to serialize as a
string and keep the decimal type at the edges. This is a demo-scale decision made
knowingly.

---

## 3. `validators.py` — the output guard

### Q11. Why a regex? An LLM would catch far more.

Schema leakage is a **syntactic** property: either the answer contains
`employees.salary` or it does not. That is a regex's job, not a judgement call.

Using a model here would turn a deterministic check into a probabilistic one —
and then nothing checks *that* model. The prompt is already a request; this layer
exists to be the guarantee. A guarantee that is right 97% of the time is not a
guarantee.

### Q12. Why not Guardrails AI? That is the standard answer.

It cannot be installed on this stack. `guardrails-ai<=0.5` requires
`langchain-core<0.3`, `>=0.6` requires `>=1.0`, and this project runs langgraph
0.2 / langchain 0.3 which needs `<0.4`. There is no version in between. Using it
meant a full langchain 1.x migration — breaking the checkpointer and graph APIs —
for one validator.

That was the *reason* to look for another way. The deterministic guard turned out
to be the better design regardless, which is a nicer outcome than it deserved.

### Q13. `_SCHEMA_ONLY` only matches `department_id`. Your schema has six columns.

On purpose, and this one line is what keeps the validator usable.

`salary`, `name`, `role`, `budget` and `location` are perfectly ordinary English
words. Flagging them would redact half of every correct answer — "the **budget**
is fixed and the **location** is Pune" would come back mangled.
`department_id` is the only column name that never occurs in natural prose, so it
is the only one safe to match unqualified.
`test_ordinary_words_are_not_flagged` is the regression test for exactly this.

### Q14. A SQL leak replaces the whole answer; the others redact in place. Why the inconsistency?

Different failures. A leaked identifier is token-level and can be removed
cleanly, leaving a correct sentence. A **whole query** in the answer means the
synthesizer did the wrong job entirely — cutting fragments out of that and
showing the remainder hands the user a partial answer that still *looks*
trustworthy. Replacing it is the safer failure.

### Q15. The prompt also says "don't list salaries for multiple people". Your validator does not enforce that.

It does not, and the module docstring says so outright rather than implying
coverage.

That rule cannot be made deterministic. "Engineering averages 101750, Sales
73000" contains two salary figures, but they are aggregates, not any
individual's pay. Separating those needs semantics, not a pattern. Pretending to
enforce it here would be worse than admitting it stays at the prompt level.

---

## 4. `data_access.py` + `mcp_client.py` — the MCP path

### Q16. **(The most important one on this path.)** Why does `run_sql` re-raise the MCP error as an exception?

Because the self-healing loop runs on **Postgres error text** — `column
"emp_name" does not exist ... HINT: ...` — and MCP delivers that error inside a
*successful* tool result, not as a transport exception.

If this layer did not convert it back, turning MCP on would **silently stop
self-healing**. No crash, no error: `execute_sql`'s `except` block would simply
never fire and the retry would never trigger. Bugs of that shape are the most
expensive kind, which is why `test_mcp_error_becomes_an_exception` exists and
asserts that the `HINT` survives intact.

### Q17. Why a background thread with its own event loop? That is a lot of machinery.

It is, and that machinery *is* the real cost of MCP. Three options were on the
table:

1. **`asyncio.run()` per call** — easiest, and worst: every SQL query spawns a
   fresh Python subprocess, ~200-300ms of pure process startup.
2. **Make the whole stack async** — correct, but a rewrite of every graph node
   and handler for the sake of one toggle.
3. **A background thread holding the session open**, with sync callers
   submitting via `run_coroutine_threadsafe`. Chosen.

The session opens once and lives for the process. The caller never learns there
is an event loop behind it.

### Q18. Then why is `USE_MCP` off by default? You built it and disabled it.

Because a direct driver call will always be faster, and the benefit of MCP is not
speed — it is that data access becomes a **swappable, standard interface**. The
default reflects what is better for the demo; the toggle reflects what the
architecture supports. Claiming MCP were always-on and faster would be the lie.

### Q19. The bridge does not JSON-decode results. Is that not the transport's job?

It was, in the first version, and it broke on `describe_schema` — which returns
plain text, not JSON.

The transport should not know the payload shape of every tool; the caller does.
So decoding moved to `data_access.py`, and `mcp_client.call()` only moves bytes.
`test_schema_is_plain_text_not_json` pins it.

---

## 5. `dashboard.py` — widget selection

### Q20. The LLM plans the questions but not the widgets. Why the split?

Because only one of those is a judgement. "What should be asked about salary" has
no single right answer — that is genuinely a model's job. "One row and one column
should be a KPI" is a **rule about the shape of the data**, and spending an LLM
call on it would turn a deterministic decision into a probabilistic one, at extra
cost and latency, with a chance of being wrong.

### Q21. `_is_part_of_whole` guesses from the column name. That is fragile.

It is, and it is fragile in a *safe direction*.

This came from a real bug: the first version gave "average salary by department"
a donut. A donut asserts "these are parts of a whole" — but averages do not add
up; the sum of four departments' average salaries represents nothing. The chart
was making a false claim about the data.

When the name heuristic guesses wrong, the result is a **bar chart**, which is
always honest. A donut is only reachable when the measure is clearly additive.
`test_averages_never_become_a_donut` is named after the bug.

### Q22. Why does every dashboard sub-question go through the full agent instead of a fast path?

Because a fast path would bypass the retry loop, the output guard and the
approval gate — putting the **least** safety on the least-watched route through
the system. The cost is real (one dashboard is 6-9 LLM calls, which is why
`MAX_WIDGETS` is 4), and it buys the guarantee that nothing reaches the database
through a door with no lock on it.

---

## 6. `checkpointer.py` / `conversations.py` — memory

### Q23. Memory fails open. Is silently running stateless not worse than erroring?

It would be, if it were silent. It is not: the API returns `memory_active`, the
UI status bar shows `memory on`/`off`, and the backend logs the reason once.

The reasoning is about blast radius. A chat app losing its memory feature is one
degraded feature; the whole app refusing to start is an outage. And the eval
harness *needs* the stateless path — every eval question must be independent, or
one question's answer changes the next one's score.

### Q24. Why does `conversations.py` use SQL for the thread list but the checkpointer's API for content?

Two different costs. The list needs only `thread_id` and a timestamp — cheap SQL,
no deserialization. The content needs LangGraph's own deserializer.

The first version tried to read the blobs directly with SQL and was **wrong**:
LangGraph stores channel values in `checkpoint_blobs` as **msgpack**, not jsonb.
Decoding that by hand means copying an internal format that breaks silently on
the next library release. The checkpointer knows what it wrote — ask it.

### Q25. Sorting on `checkpoint->>'ts'` instead of the thread id. Why the extra work?

Thread ids do contain a timestamp, but they are **generated by the client**. A
different client with a different id format would silently reorder the sidebar.
The checkpoint timestamp is written by the server, so it is the only one that can
be trusted for ordering.

### Q26. `delete_conversation` hits three tables. Is deleting from `checkpoints` not enough?

No — that leaves orphaned rows in `checkpoint_writes` and `checkpoint_blobs`,
which recreates exactly the condition this module was written to fix: **data that
exists but cannot be reached**.

---

## 7. Infrastructure

### Q27. The rate limiter is a dict of deques. That breaks the moment you run two replicas.

Correct, and it is stated in the module docstring rather than discovered in
production. Each process would keep its own counters, so N replicas means N times
the limit.

It is the right call for a single-container demo — no Redis, no extra service,
no dependency — and the wrong call for anything multi-replica. The fix at that
point is a shared store, not a bigger dict. There is also a `MAX_TRACKED_IPS`
ceiling, because an unbounded dict keyed by user-controlled values is a memory
leak with extra steps.

### Q28. The seed data is random. How are your eval numbers reproducible?

It is **seeded** random — `random.Random(42)`, fixed. Every machine generates the
same 160 employees, 8 departments and 10 projects.

That is not a detail. If the seed drifted, no accuracy number could be compared
with a previous run, and "self-healing improved accuracy by 15 points" would mean
nothing at all.

### Q29. Why hand-write `get_schema_description()` instead of introspecting `information_schema`?

Because the description carries two things introspection cannot: **example
values** (so the model knows what a department actually looks like) and an
explicit statement that `employees` has no department-name column, so a join is
mandatory. Those are what stop the model inventing `employees.department`.

It is also why this does not scale past ~30 tables — stated in
[ROADMAP.md](ROADMAP.md) as schema retrieval, the next real problem.

### Q30. `/api/meta` exposes your model name and write mode. Is that not leaking configuration?

Nothing there is secret — it is the same information the README states openly,
and showing it is what lets a reader tell a demo running in safe mode apart from
one that is committing writes.

The reason it exists is more interesting than what it shows: the UI used to
hard-code "PostgreSQL 18" in a component. A status bar that cannot go out of date
is a status bar nobody ever checked. This one caught its own first bug
immediately — the running model was `gemini-3.1-flash-lite` while every doc said
`3.5`.

---

## 8. Eval — expect the most follow-ups here

### Q31. Your headline result is +0pp. Why is that on the front page?

Because it is the truth, and because it locates precisely where the architecture
earns its cost.

With a well-tuned schema description the model never produced SQL that Postgres
rejected — `avg_retries = 0.00` across 20 questions. The loop never fired, so it
contributed exactly nothing. Publishing that is the difference between a
measurement and a marketing claim.

The result that matters sits next to it: degrade the schema description to
something stale and accuracy goes **15% → 30%** with 2.25 average retries. The
loop pays for itself against **schema drift**, not against prompt quality. That
is a sharper claim than "it makes the agent better".

### Q32. Twenty questions is a tiny sample. What is 15% → 30% worth statistically?

Very little on its own — that is 3 questions versus 6, and the confidence
interval is wide enough to drive through. It is directional evidence, not proof,
and it should be described that way.

This is exactly why Spider ranks above every remaining feature in the roadmap: a
standard benchmark with labelled gold queries at real schema scale is the only
thing that turns this into a claim worth defending numerically.

### Q33. You wrote the questions and the gold SQL yourself. Is that not circular?

Partly, yes. The mitigation is that the **metric** is not self-graded: execution
accuracy compares returned rows against the gold query's rows, so a wrong query
that happens to look plausible still fails. There is no LLM judge anywhere in the
scoring.

The remaining bias is in question *selection* — I chose what to ask. A benchmark I
did not write is the fix, which is the same answer as Q32.

### Q34. Why execution accuracy rather than comparing the SQL strings?

Because string match fails correct answers. `SELECT name FROM employees WHERE
salary > 80000` and `SELECT e.name FROM employees e WHERE e.salary > 80000` are
the same query and would not match. Aliases, join order and column order all vary
without changing the result.

There is a real weakness: two different queries can return identical rows by
coincidence on a small dataset. Both a strict and a relaxed "contains" metric are
reported so that gap is visible rather than papered over — the relaxed one exists
because the strict metric failed an answer that was *correct* but returned extra
columns.

---

## Related

| | |
|---|---|
| [CODE_NOTES.md](CODE_NOTES.md) | Why each file and dependency exists |
| [INTERVIEW_NOTES.md](INTERVIEW_NOTES.md) | The pitch, the trade-offs, and the hostile questions |
| [TEXT_TO_SQL_FUNDAMENTALS.md](TEXT_TO_SQL_FUNDAMENTALS.md) | The concepts underneath, and general interview prep |
| [eval/RESULTS.md](../eval/RESULTS.md) | The numbers behind section 8 |
