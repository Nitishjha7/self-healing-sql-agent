"""Phase 5 — turning one request into a whole dashboard.

Take a single sentence like "Create a dashboard showing department-wise salary and
headcount", break it into smaller questions, run each one through **the same
self-healing agent**, and pick a widget for each result.

**Two decisions shape this entire file:**

1. **The LLM plans the sub-questions, not the widgets.** The questions involve
   judgement — there is no single right answer to "what should be asked about
   salary". The widget does not: one row and one column means a KPI, four
   categories means a bar. That follows from the **shape** of the data, and
   spending another LLM call on it would turn a deterministic decision into a
   probabilistic one.

2. **Every sub-question goes through the full agent**, never a shortcut. That
   means the retry loop, the output guard and the approval gate all apply exactly
   as they normally do. If the dashboard had its own SQL path, all of that would
   be bypassed, and the least-watched route through the system would have the
   least safety.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.data_access import get_schema_description
from app.graph import run_agent
from app.nodes import _llm

# How many widgets one dashboard may have. Each widget is a full agent run (1-2
# LLM calls, more when it retries), and the free tier allows ~15 requests/minute.
# At four, a dashboard costs ~6-9 calls — which fits inside that quota. Any higher
# and the first dashboard would consume the whole allowance.
MAX_WIDGETS = int(os.environ.get("DASHBOARD_MAX_WIDGETS", "4"))

_PLANNER_SYSTEM = (
    "You plan dashboards over a SQL database. Given a request and a schema, you "
    "return the questions a dashboard should answer — nothing else. Each question "
    "must be answerable by a single SQL query against the given schema, and must "
    "be phrased in plain English, as a person would ask it. Prefer a mix: one "
    "headline number, one comparison across a category, one breakdown. Never ask "
    "for data the schema does not contain."
)


def _plan(request: str, limit: int) -> list[str]:
    """Break the request into sub-questions.

    A JSON array is requested and parsed defensively — the model sometimes adds a
    code fence or a one-line preamble. A failed parse returns an empty list, which
    the caller turns into a clear message; saying plainly that no plan could be
    made beats showing a half-built dashboard.
    """
    schema = get_schema_description()
    response = _llm().invoke(
        [
            SystemMessage(content=_PLANNER_SYSTEM),
            HumanMessage(
                content=(
                    f"Schema:\n{schema}\n\n"
                    f"Dashboard request: {request}\n\n"
                    f"Return at most {limit} questions as a JSON array of strings. "
                    "Return only the JSON array."
                )
            ),
        ]
    )

    text = response.content.strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        questions = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []

    return [q.strip() for q in questions if isinstance(q, str) and q.strip()][:limit]


# Measure names that **can be added up** — a total of these means something.
_ADDITIVE = ("count", "total", "sum", "headcount", "num", "spend", "budget", "payroll")

# Measure names that **cannot** be added up. Summing averages, rates or
# percentages is meaningless.
_NON_ADDITIVE = ("avg", "average", "mean", "median", "rate", "percent", "pct", "ratio")


def _is_part_of_whole(column: str) -> bool:
    """Whether a total of this measure means anything — i.e. whether a donut is honest.

    **This check did not exist at first, and the bug showed up in the very first
    real dashboard:** "average salary by department" got a donut. A donut says
    "these are parts of a whole", but averages do not add up — the sum of four
    departments\u2019 average salaries represents nothing. That chart made a claim
    about the data that was not true.

    Guessing from the name is not perfect (`salary` on its own is ambiguous), but
    when it guesses wrong the result is a bar chart — which is always honest. A
    donut is only used when the measure is clearly additive.
    """
    lowered = column.lower()
    if any(word in lowered for word in _NON_ADDITIVE):
        return False
    return any(word in lowered for word in _ADDITIVE)


def choose_widget(rows: list[dict]) -> str:
    """Pick a widget from the shape of the result set. No LLM — this is not judgement.

    The rules, in this order:

    - one row, one column                            -> `kpi`   (charting a single number is decoration)
    - two columns, second additive numeric, <= 6 rows -> `donut` (parts of a whole)
    - two columns, second numeric                    -> `bar`   (comparing categories)
    - anything else                                  -> `table` (do not plot what does not plot)

    The cap of 6 for a donut: beyond that, slices stop being readable by arc
    length and the legend becomes the chart — a bar is the honest choice there.
    """
    if not rows:
        return "empty"

    columns = list(rows[0].keys())

    if len(rows) == 1 and len(columns) == 1:
        return "kpi"

    if len(columns) == 2:
        second = rows[0][columns[1]]
        # `bool` is a subclass of `int` in Python — without this check a
        # true/false column would be plotted as a magnitude.
        numeric = isinstance(second, (int, float)) and not isinstance(second, bool)
        if numeric:
            if len(rows) <= 6 and _is_part_of_whole(columns[1]):
                return "donut"
            return "bar"

    return "table"


def build_dashboard(request: str, thread_id: Optional[str] = None) -> dict:
    """Build a dashboard from one request.

    `thread_id` is passed straight through to the agent, so the dashboard\u2019s
    questions are recorded in the same conversation — asking "what was the
    Engineering number in that dashboard?" afterwards works.
    """
    questions = _plan(request, MAX_WIDGETS)
    if not questions:
        return {
            "request": request,
            "title": request,
            "widgets": [],
            "error": (
                "Couldn't turn that into questions this database can answer. "
                "Try naming the tables or measures you care about."
            ),
        }

    widgets = []
    for question in questions:
        result = run_agent(question, thread_id=thread_id)
        rows = result.get("result_rows") or []

        # An approval gate or a failure — nothing to build a widget from. Rather
        # than drop it, record it: a dashboard that silently has one widget fewer
        # is worse than one that says a question could not be answered.
        if result.get("approval_status") == "pending":
            widgets.append(
                {
                    "question": question,
                    "type": "skipped",
                    "note": "This question needed a write, so it was not run here.",
                    "sql": result.get("sql_query", ""),
                }
            )
            continue

        if result.get("error") or not rows:
            widgets.append(
                {
                    "question": question,
                    "type": "empty",
                    "note": result.get("final_answer")
                    or "No rows came back for this question.",
                    "sql": result.get("sql_query", ""),
                    "retry_count": result.get("retry_count", 0),
                }
            )
            continue

        widgets.append(
            {
                "question": question,
                "type": choose_widget(rows),
                "rows": rows,
                "row_count": result.get("row_count", len(rows)),
                "answer": result.get("final_answer", ""),
                "sql": result.get("sql_query", ""),
                "retry_count": result.get("retry_count", 0),
            }
        )

    return {
        "request": request,
        "title": _title(request),
        "widgets": widgets,
        "thread_id": thread_id,
    }


def _title(request: str) -> str:
    """Turn the request into a short title — without an LLM call.

    Spending another model call on a heading is a poor use of quota, and getting a
    heading slightly wrong costs just as little. Strip the prefixes and keep the
    first clause.
    """
    text = re.sub(
        # `me` is its own optional group: both "show me ..." and "give me ..."
        # occur, and folding it into the verb would miss one of them.
        r"^(create|make|build|show|give|display)\s+(me\s+)?(a|an|the)?\s*"
        r"(dashboard|report|overview)?\s*(showing|for|of|with|about)?\s*",
        "",
        request.strip(),
        flags=re.IGNORECASE,
    )
    text = text.split(".")[0].strip(" ,") or request.strip()
    return (text[:1].upper() + text[1:])[:70]
