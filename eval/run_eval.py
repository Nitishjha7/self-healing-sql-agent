"""Evaluation harness for the Self-Healing SQL Agent.

Metric: **execution accuracy** — the standard Text-to-SQL measure. We don't compare
the agent's SQL string to a gold SQL string (many different queries are equally
correct), and we don't ask an LLM to judge the answer (that just moves the
reliability problem somewhere unmeasurable). Instead we execute both the gold
query and the agent's query and compare the result sets.

The headline number this produces: accuracy with the self-healing loop on
(MAX_RETRIES=3) vs off (MAX_RETRIES=0), on the same questions. That delta is the
entire business case for the architecture.

Usage (from the project root, with the db container running):

    docker compose up -d db
    docker compose run --rm --no-deps \
        -v "$PWD/eval:/app/eval" \
        -e DATABASE_URL=postgresql://agent:agent@db:5432/employees \
        backend python -m eval.run_eval

Flags:
    --retries 0 3     which MAX_RETRIES settings to evaluate (default: 0 and 3)
    --delay 4.0       seconds to wait between questions (free-tier rate limits)
    --limit 5         only run the first N questions (quick smoke test)
    --out results.json
"""

from __future__ import annotations

import argparse
import json
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import app.graph as graph_mod
from app.db import init_db, run_sql

QUESTIONS_PATH = Path(__file__).parent / "questions.json"

# Free-tier quotas are small and a self-healing run can issue up to 5 LLM calls,
# so a 429 mid-eval is expected rather than exceptional. We back off and retry the
# whole question instead of letting one rate limit invalidate the run.
RATE_LIMIT_MARKERS = ("429", "resourceexhausted", "quota", "rate limit")
MAX_BACKOFF_ATTEMPTS = 5


def _is_rate_limited(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


def _normalize(value: Any) -> Any:
    """Make values comparable across equivalent-but-differently-typed results.

    Postgres returns AVG as Decimal and COUNT as int; an agent query that casts
    or rounds differently is still correct. Numbers are compared at 2dp, strings
    are stripped, everything else falls back to its string form.
    """
    if isinstance(value, (Decimal, float, int)) and not isinstance(value, bool):
        return round(float(value), 2)
    if isinstance(value, str):
        return value.strip()
    return str(value)


def _row_sets(rows: list[dict]) -> list[frozenset]:
    """Each row as an order-insensitive set of normalized values.

    Column *names* are ignored — the agent aliasing a column differently is not
    an error.
    """
    return [frozenset(_normalize(v) for v in row.values()) for row in rows]


def _strict_match(gold: list[dict], agent: list[dict]) -> bool:
    """Exact set-of-rows equality — the classic Text-to-SQL execution accuracy."""
    return set(_row_sets(gold)) == set(_row_sets(agent))


def _contains_match(gold: list[dict], agent: list[dict]) -> bool:
    """Relaxed: the agent's result must *contain* the gold answer.

    Same row count, and every gold row maps to a distinct agent row whose values
    are a superset of it. This exists because the questions genuinely do not
    specify which columns to project — "Who is the highest paid employee?"
    is answered correctly by `SELECT name` and equally correctly by
    `SELECT name, salary, role`. Penalising the second is measuring prompt
    compliance, not SQL correctness.

    Greedy matching, largest gold rows first. Exact bipartite matching would be
    more rigorous but is overkill at this result size.
    """
    gold_sets, agent_sets = _row_sets(gold), _row_sets(agent)
    if len(gold_sets) != len(agent_sets):
        return False

    remaining = list(agent_sets)
    for g in sorted(gold_sets, key=len, reverse=True):
        match = next((a for a in remaining if g <= a), None)
        if match is None:
            return False
        remaining.remove(match)
    return True


# A bare column listing with no relationship line, no example values, and no
# "you must join" warning. This is what a schema description looks like when it
# is generated from introspection instead of hand-tuned — i.e. what most real
# deployments actually have. Running the eval against this is how we measure the
# self-healing loop under conditions where it has something to heal.
DEGRADED_SCHEMA = (
    "Table: departments\n"
    "Columns: id, name, budget, location\n"
    "\n"
    "Table: employees\n"
    "Columns: id, name, department_id, salary, role\n"
)


def _degraded_schema() -> str:
    return DEGRADED_SCHEMA


def _run_one(question: str, delay: float) -> dict:
    """Run the agent once, retrying the whole question through rate limits."""
    for attempt in range(MAX_BACKOFF_ATTEMPTS):
        try:
            return graph_mod.run_agent(question)
        except Exception as exc:  # noqa: BLE001 — we re-raise below if not a 429
            if not _is_rate_limited(exc) or attempt == MAX_BACKOFF_ATTEMPTS - 1:
                raise
            backoff = delay * (2 ** attempt) + 5
            print(f"      rate limited, backing off {backoff:.0f}s...", flush=True)
            time.sleep(backoff)
    raise RuntimeError("unreachable")


def evaluate(questions: list[dict], max_retries: int, delay: float) -> dict:
    """Run every question at a given MAX_RETRIES setting."""
    # graph.py reads MAX_RETRIES as a module global at call time, so patching the
    # attribute is enough to change the retry budget between runs in-process.
    graph_mod.MAX_RETRIES = max_retries

    results = []
    print(f"\n{'=' * 70}\nMAX_RETRIES = {max_retries}\n{'=' * 70}")

    for i, item in enumerate(questions, 1):
        gold_rows = run_sql(item["gold_sql"])

        record = {
            "id": item["id"],
            "question": item["question"],
            "tags": item.get("tags", []),
            "correct": False,
            "strict_correct": False,
            "retry_count": None,
            "agent_sql": None,
            "error": None,
        }

        try:
            state = _run_one(item["question"], delay)
            record["agent_sql"] = state["sql_query"]
            record["retry_count"] = state["retry_count"]

            if state.get("error"):
                record["error"] = state["error"]
            else:
                agent_rows = run_sql(state["sql_query"])
                record["correct"] = _contains_match(gold_rows, agent_rows)
                record["strict_correct"] = _strict_match(gold_rows, agent_rows)
        except Exception as exc:  # noqa: BLE001 — a crash is a failed question
            record["error"] = f"{type(exc).__name__}: {exc}"

        mark = "PASS" if record["correct"] else "FAIL"
        retries = record["retry_count"]
        retry_note = f" (retries: {retries})" if retries else ""
        print(f"  [{i:>2}/{len(questions)}] {mark}{retry_note}  {item['question']}")
        if record["error"]:
            print(f"        error: {record['error'][:120]}")

        results.append(record)
        if i < len(questions):
            time.sleep(delay)

    passed = sum(r["correct"] for r in results)
    strict_passed = sum(r["strict_correct"] for r in results)
    total = len(results)
    healed = [r for r in results if r["correct"] and (r["retry_count"] or 0) > 0]

    return {
        "max_retries": max_retries,
        "passed": passed,
        "strict_passed": strict_passed,
        "total": total,
        "accuracy": passed / total if total else 0.0,
        "strict_accuracy": strict_passed / total if total else 0.0,
        "avg_retries": (
            sum(r["retry_count"] or 0 for r in results) / total if total else 0.0
        ),
        "healed_count": len(healed),
        "healed_ids": [r["id"] for r in healed],
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the Self-Healing SQL Agent.")
    parser.add_argument("--retries", type=int, nargs="+", default=[0, 3])
    parser.add_argument("--delay", type=float, default=4.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default="eval/results.json")
    parser.add_argument(
        "--degrade-schema",
        action="store_true",
        help="Strip the hand-tuned hints from the schema description, so the "
        "agent has to infer joins the way it would against a real introspected "
        "schema. This is the run where the self-healing loop actually matters.",
    )
    args = parser.parse_args()

    init_db()

    if args.degrade_schema:
        # graph.py imported the function by name, so patch it on graph, not db.
        graph_mod.get_schema_description = _degraded_schema
        print("Schema: DEGRADED (no relationship hints, no example values)")
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    if args.limit:
        questions = questions[: args.limit]

    print(f"Model: {os.environ.get('GEMINI_MODEL', graph_mod.GEMINI_MODEL)}")
    print(f"Questions: {len(questions)} | delay: {args.delay}s")

    runs = [evaluate(questions, r, args.delay) for r in args.retries]

    print(f"\n{'=' * 70}\nSUMMARY\n{'=' * 70}")
    print(
        f"{'MAX_RETRIES':>12} | {'Accuracy':>18} | {'Strict':>18} | "
        f"{'Avg retries':>11} | {'Healed':>6}"
    )
    print(f"{'-' * 12}-+-{'-' * 18}-+-{'-' * 18}-+-{'-' * 11}-+-{'-' * 6}")
    for run in runs:
        acc = f"{run['passed']}/{run['total']} ({run['accuracy']:.0%})"
        strict = f"{run['strict_passed']}/{run['total']} ({run['strict_accuracy']:.0%})"
        print(
            f"{run['max_retries']:>12} | {acc:>18} | {strict:>18} | "
            f"{run['avg_retries']:>11.2f} | {run['healed_count']:>6}"
        )

    if len(runs) > 1:
        baseline, best = runs[0], runs[-1]
        delta = best["accuracy"] - baseline["accuracy"]
        print(
            f"\nSelf-healing delta: {baseline['accuracy']:.0%} -> {best['accuracy']:.0%} "
            f"({delta:+.0%})"
        )
        if best["healed_ids"]:
            print(f"Questions fixed by retrying: {best['healed_ids']}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(runs, indent=2), encoding="utf-8")
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
