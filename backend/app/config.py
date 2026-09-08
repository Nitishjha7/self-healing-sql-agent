"""Environment-driven configuration.

Separate from `state.py` because these are settings, not shape — and because
two of them are **changed at runtime**: the eval harness sweeps `MAX_RETRIES`
to measure what the self-healing loop contributes, and the tests flip
`ALLOW_WRITES` to check both sides of the approval gate. Node code therefore
reads them as `config.MAX_RETRIES` rather than importing the values, so a patch
on this module is actually seen.

Every one of these is an environment variable rather than a literal, and each
had a reason. `GEMINI_MODEL` especially: Google retired two model ids during
this project's life, and a hard-coded model name is a time bomb in any LLM app.
"""

import os

# Eval harness isko 0 set karke measure karta hai ki self-healing loop ke bina
# accuracy kitni girti hai.
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))

# Model versions deprecate hote rehte hain, aur eval me alag models compare
# karne ke liye bhi kaam aata hai.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

BLOCKED_KEYWORDS = ("DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE")

# Approved write ko sach me commit karna hai ya nahi.
#
# `false` (default) pe approved query phir bhi **chalti** hai — Postgres use plan
# karta hai, constraints check karta hai, affected rows batata hai — aur phir
# rollback ho jaati hai. Isse approval flow public demo pe bhi dikhaya ja sakta
# hai bina kisi visitor ko `DELETE FROM employees` chalane ki taakat diye.
#
# Ye "approval ka dikhava" nahi hai: user ko response me saaf likha jaata hai ki
# rollback hua aur kitni rows par asar padta. Jhoot bolna aur cheez hai, safe
# mode me chalana aur.
ALLOW_WRITES = os.environ.get("ALLOW_WRITES", "").lower() in ("1", "true", "yes")

# Ek conversation me kitne pichhle turns prompt me bhejne hain. Poori history
# bhejna do tarah se mehnga hai — tokens, aur dhyaan: bees turn purani baat
# aksar current sawaal se koi rishta nahi rakhti, par model use context maan ke
# usme se entities utha leta hai. Teen follow-up chain ke liye kaafi hai.
HISTORY_TURNS_IN_PROMPT = int(os.environ.get("HISTORY_TURNS_IN_PROMPT", "3"))

# UI ko dikhane ke liye kitni rows bhejni hain. Ye rows checkpointer me likhi
# jaati hain, to bina cap ke ek "SELECT * FROM employees" poori table ko har
# conversation checkpoint me daal deta.
MAX_RESULT_ROWS = 50
