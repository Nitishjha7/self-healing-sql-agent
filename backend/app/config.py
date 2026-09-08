"""Environment-driven configuration.

Separate from `state.py` because these are settings, not shape — and because two
of them are **changed at runtime**: the eval harness sweeps `MAX_RETRIES` to
measure what the self-healing loop contributes, and the tests flip `ALLOW_WRITES`
to check both sides of the approval gate. Node code therefore reads them as
`config.MAX_RETRIES` rather than importing the values, so a patch on this module
is actually seen.

Every one of these is an environment variable rather than a literal, and each had
a reason. `GEMINI_MODEL` especially: Google retired two model ids during this
project's life, and a hard-coded model name is a time bomb in any LLM app.
"""

import os

# The eval harness sets this to 0 to measure how far accuracy falls without the
# self-healing loop.
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))

# Model ids get retired, and being able to compare models is useful in the eval.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

BLOCKED_KEYWORDS = ("DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE")

# Whether an approved write is actually committed.
#
# Left `false` (the default) an approved statement still **runs** — Postgres plans
# it, enforces every constraint, and reports the rows it would have touched — and
# is then rolled back. That is what makes the approval flow demonstrable on a
# public deployment without handing any visitor the ability to run
# `DELETE FROM employees`.
#
# This is not approval theatre: the response says plainly that the statement was
# rolled back and how many rows it would have affected. Running in a safe mode and
# saying so is a different thing from claiming an action happened.
ALLOW_WRITES = os.environ.get("ALLOW_WRITES", "").lower() in ("1", "true", "yes")

# How many prior turns to render into the prompt. Sending everything is expensive
# in two ways — tokens, and attention: a twenty-turn-old exchange usually has
# nothing to do with the current question, yet the model treats it as context and
# lifts entities out of it. Three is enough for a chain of follow-ups.
HISTORY_TURNS_IN_PROMPT = int(os.environ.get("HISTORY_TURNS_IN_PROMPT", "3"))

# How many rows to hand back for display. These rows are written into the
# checkpointer, so without a cap a single "SELECT * FROM employees" would put the
# whole table into every conversation checkpoint.
MAX_RESULT_ROWS = 50
