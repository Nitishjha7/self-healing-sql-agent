# Evaluation Harness

Measures whether the self-healing loop actually works — and by how much.

## The metric: execution accuracy

We do **not** compare the agent's SQL string to a gold SQL string. Many different
queries answer the same question correctly, so string comparison measures
stylistic agreement, not correctness.

We also do **not** use an LLM to judge the answer. That would move the reliability
problem into a component we cannot measure, which defeats the purpose of having an
eval at all.

Instead: **run both queries and compare the result sets.** This is the standard
Text-to-SQL execution accuracy metric.

### Two numbers, deliberately

| Metric | Rule | What it measures |
|---|---|---|
| **Accuracy** (headline) | Same row count, and every gold row's values appear as a subset of a distinct agent row | Did the agent find the right answer? |
| **Strict** | Exact set-of-rows equality | Did it also project exactly the expected columns? |

The relaxed metric exists because the questions genuinely do not specify which
columns to return. *"Who is the highest paid employee?"* is answered correctly by
`SELECT name` and equally correctly by `SELECT name, salary, role`. Scoring the
second as wrong measures prompt compliance, not SQL correctness — so that belongs
in the strict column, not the headline.

Column *names* are ignored in both (aliasing is not an error). Numbers are
compared at 2 decimal places, so `AVG` returning `Decimal` vs a rounded `float`
still matches.

## Running it

```bash
docker compose up -d db

docker compose run --rm --no-deps \
    -v "$PWD/eval:/app/eval" \
    backend python -m eval.run_eval
```

On Windows PowerShell, pass the absolute host path to `-v` instead of `$PWD`.

| Flag | Default | Purpose |
|---|---|---|
| `--retries 0 3` | `0 3` | Which `MAX_RETRIES` settings to evaluate |
| `--delay 4.0` | `4.0` | Seconds between questions (free-tier rate limits) |
| `--limit N` | all | Only run the first N questions (smoke test) |
| `--out PATH` | `eval/results.json` | Where to write full results |
| `--degrade-schema` | off | Strip the hand-tuned schema hints (see below) |

Override the model with `-e GEMINI_MODEL=...`. Quotas are **per model**, so
switching models gives a fresh daily allowance.

## Why `--retries 0` is the whole point

`MAX_RETRIES=0` disables the self-healing loop: the agent generates SQL once, and
a failure stays a failure. `MAX_RETRIES=3` is the real system. Running the same
20 questions under both settings isolates the contribution of the architecture
from the contribution of the model.

`graph.py` reads `MAX_RETRIES` as a module global at call time, so the harness
patches the attribute between runs rather than restarting the process.

## `--degrade-schema`: measuring the loop where it actually matters

The production `get_schema_description()` is hand-tuned. It carries example
values, an explicit `employees.department_id -> departments.id` relationship
line, and a direct statement that `employees` has no department-name column so a
join is mandatory. With that much guidance, a competent model rarely writes a
failing query — so the self-healing loop rarely fires, and an eval against it
measures the *prompt*, not the *architecture*.

`--degrade-schema` replaces it with a bare column listing — no relationship line,
no example values, no join warning. That is what a schema description looks like
when it comes from introspection rather than hand-tuning, which is what most real
deployments actually have.

Running both conditions answers two different questions:

| Run | Question it answers |
|---|---|
| Normal schema, retries 0 vs 3 | Does the loop help when the prompt is already good? |
| Degraded schema, retries 0 vs 3 | **Does the loop recover accuracy when the prompt is realistic?** |

The second is the honest test of the architecture. A loop that only helps on a
prompt you already tuned to death is not doing much work.

## Rate limiting

Gemini free-tier quotas are small — some models allow only **20 requests per
day** — and a single self-healing run can issue up to 5 LLM calls. A 429 mid-eval
is expected rather than exceptional, so the harness backs off exponentially and
retries the whole question. If a question still fails after 5 backoff attempts it
is recorded as an error, not silently dropped.

Prefer a `-lite` model for eval runs: same routing behaviour, much larger free
allowance.

## Files

| File | Purpose |
|---|---|
| `questions.json` | 20 questions with gold SQL and difficulty tags |
| `run_eval.py` | The harness |
| `results.json` | Full per-question output (generated) |

Every gold query is validated against the live schema before use — a broken gold
query would silently corrupt the metric.

## Why the data is synthetic, and what would make this harder

The rows are generated, not imported. `random.Random(42)` is fixed, so every
machine builds the identical dataset — without that, a change in accuracy between
runs would be indistinguishable from a change in the data, and comparing the three
conditions would mean nothing.

The schema is shaped for the task too: `employees` has no department-name column,
so a join must be inferred. Most public HR datasets are a single flat CSV, which
would remove the join entirely — and with it the class of error this loop repairs.

**What would genuinely raise the difficulty is a larger schema, not more realistic
data.** [Spider](https://yale-lily.github.io/spider) is the standard Text-to-SQL
benchmark and ships labelled gold queries, so this harness would need a loader
rather than a rewrite — the execution-accuracy metric transfers unchanged. It
answers the question these three conditions cannot: at thirty-plus tables, does an
error-informed retry loop still help, or do failures shift from syntactic to
semantic — valid SQL answering the wrong question — where the loop is blind?
