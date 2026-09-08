"""Deterministic output validation on the final answer.

**Why not Guardrails AI.** Tried twice, hit a dependency wall both times:
`guardrails-ai<=0.5` requires `langchain-core<0.3`, `>=0.6` requires
`langchain-core>=1.0`, and this project runs langgraph 0.2 / langchain 0.3 which
needs `langchain-core<0.4`. There is no version in between. Using it would have
meant a full langchain 1.x migration — breaking the checkpointer and graph APIs
— for the sake of one validator.

**And a deterministic check is the better fit here anyway.** Schema leakage is a
*syntactic* property: either the answer contains `employees.salary` or it does
not. That is a job for a regex, not for judgement. Adding another LLM for it
would turn a deterministic check into a probabilistic one — and then who checks
that LLM.

**What this enforces:**
- Qualified identifiers (`employees.salary`, `e.name`, `d.budget`)
- Schema-specific column names (`department_id`) that never occur in plain English
- SQL that leaked into the answer

**What it deliberately does NOT enforce, and why:** the synthesis prompt also
says not to give salary figures for more than one person unless asked to
compare. That rule cannot be made deterministic — "Engineering averages 101750,
Sales 73000" has two figures, but they are aggregates, not any individual's
salary. Separating those needs semantics, not a pattern. Rather than pretend to
enforce it here, it is honest to say that rule stays at the prompt level.
"""

from __future__ import annotations

import re

TABLES = ("employees", "departments")
COLUMNS = ("id", "name", "department_id", "salary", "role", "budget", "location")

# `employees.salary`, `e.name`, `d.budget` — a known column behind a table name
# or a single-letter alias. A generic `\w+\.\w+` was deliberately avoided: it
# matches "e.g." and every sentence boundary. Building the pattern from the real
# schema names removes almost all false positives.
_QUALIFIED = re.compile(
    r"\b(?:" + "|".join(TABLES) + r"|[a-z])\.(" + "|".join(COLUMNS) + r")\b",
    re.IGNORECASE,
)

# Only column names that do not occur in ordinary English. `salary`, `name`,
# `role`, `budget` and `location` are perfectly normal words — flagging them
# would break every correct answer. This one line is what keeps the validator
# usable at all.
_SCHEMA_ONLY = re.compile(r"\bdepartment_id\b", re.IGNORECASE)

_SQL_FRAGMENT = re.compile(r"\bSELECT\b[\s\S]{0,200}?\bFROM\b", re.IGNORECASE)

# A SQL leak replaces the answer rather than redacting it. The other leaks are
# token-level and can be removed cleanly; a whole query in the answer means the
# synthesizer did the wrong job entirely — cutting pieces out of it and showing
# the remainder would hand the user a partial answer that still looks
# trustworthy.
_SQL_LEAK_REPLACEMENT = (
    "I found the answer, but couldn't phrase it without exposing internal "
    "query details. Please try asking again."
)


def validate_answer(answer: str) -> tuple[str, list[str]]:
    """Clean the answer and report everything that was found.

    Redact-and-flag, not block. A leaked schema name is low severity — killing a
    correct answer over it is worse for the user than the leak itself. But
    fixing it silently would be wrong too: the flags travel out in the API
    response, so it is visible that the guard fired rather than merely assumed.
    """
    flags: list[str] = []

    if _SQL_FRAGMENT.search(answer):
        return _SQL_LEAK_REPLACEMENT, ["sql_in_answer"]

    if _QUALIFIED.search(answer):
        flags.append("qualified_identifier")
        answer = _QUALIFIED.sub(lambda m: m.group(1), answer)

    if _SCHEMA_ONLY.search(answer):
        flags.append("schema_column_name")
        answer = _SCHEMA_ONLY.sub("department", answer)

    return answer, flags
