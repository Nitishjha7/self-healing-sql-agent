"""Final answer par deterministic output validation.

**Guardrails AI kyun nahi.** Do baar koshish ki, dono baar dependency wall:
`guardrails-ai<=0.5` `langchain-core<0.3` maangta hai, `>=0.6` `langchain-core>=1.0`
maangta hai, aur ye project langgraph 0.2 / langchain 0.3 pe hai jise
`langchain-core<0.4` chahiye. Beech me koi version hai hi nahi. Use karne ke liye
poora langchain 1.x migration karna padta — jo checkpointer aur graph APIs tod
deta — sirf ek validator ke liye.

**Aur yahan deterministic check waise bhi behtar hai.** Schema leakage ek
*syntactic* baat hai: jawab me `employees.salary` likha hai ya nahi. Ye ek regex
ka kaam hai, judgement ka nahi. Iske liye ek aur LLM lagana matlab ek
deterministic check ko probabilistic bana dena — aur us naye LLM ko kaun check
karega.

**Jo ye enforce karta hai:**
- Qualified identifiers (`employees.salary`, `e.name`, `d.budget`)
- Schema-specific column names (`department_id`) jo aam angrezi me kabhi nahi aate
- Answer me ghusi hui SQL

**Jo ye enforce NAHI karta, aur kyun:** synthesis prompt ye bhi kehta hai ki ek se
zyada logon ki salary figures na do jab tak compare karne ko na bola ho. Wo rule
deterministic nahi ho sakta — "Engineering ka average 101750 hai, Sales ka 73000"
me do figures hain par wo aggregate hain, kisi vyakti ki salary nahi. Dono ko alag
karne ke liye semantics chahiye, pattern nahi. Us rule ko yahan enforce karne ka
dikhava karne se behtar hai ye maan lena ki wo abhi prompt-level hi hai.
"""

from __future__ import annotations

import re

TABLES = ("employees", "departments")
COLUMNS = ("id", "name", "department_id", "salary", "role", "budget", "location")

# `employees.salary`, `e.name`, `d.budget` — table ya single-letter alias ke saath
# ek jaana-pehchana column. Generic `\w+\.\w+` jaan-boojh ke nahi liya: wo "e.g."
# aur har sentence-boundary pe lag jaata. Schema ke asli naamon se pattern banane
# se false positive lagbhag khatam ho jaate hain.
_QUALIFIED = re.compile(
    r"\b(?:" + "|".join(TABLES) + r"|[a-z])\.(" + "|".join(COLUMNS) + r")\b",
    re.IGNORECASE,
)

# Sirf wahi column naam jo aam angrezi me nahi aate. `salary`, `name`, `role`,
# `budget`, `location` bilkul normal shabd hain — unhe flag karna har sahi jawab
# ko tod dega. Ye line hi is validator ko istemaal ke laayak rakhti hai.
_SCHEMA_ONLY = re.compile(r"\bdepartment_id\b", re.IGNORECASE)

_SQL_FRAGMENT = re.compile(r"\bSELECT\b[\s\S]{0,200}?\bFROM\b", re.IGNORECASE)

# SQL leak pe jawab redact nahi karte, badal dete hain. Baaki leaks token-level
# hain aur nikaale ja sakte hain; poori query answer me aa jaana matlab
# synthesizer ne kaam hi galat kiya — usme se tukde kaat kar bacha hua text
# dikhana user ko ek adhoora, bharosemand-dikhne wala jawab de deta.
_SQL_LEAK_REPLACEMENT = (
    "I found the answer, but couldn't phrase it without exposing internal "
    "query details. Please try asking again."
)


def validate_answer(answer: str) -> tuple[str, list[str]]:
    """Answer ko saaf karta hai aur jo bhi mila uski list deta hai.

    Redact-and-flag rakha hai, block nahi. Schema naam leak hona low severity hai
    — ek sahi jawab ko uske liye maar dena user ke liye leak se zyada bura hai.
    Lekin chup-chaap theek kar dena bhi galat hai: flags API response me jaate
    hain, taaki ye dikhe ki guard laga tha, na ki sirf maan liya jaaye.
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
