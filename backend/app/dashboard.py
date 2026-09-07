"""Phase 5 — ek request se poora dashboard banana.

"Create a dashboard showing department-wise salary and headcount" jaisa ek vaakya
lete hain, use chhote sawaalon me todte hain, har sawaal ko **usi self-healing
agent** se chalate hain, aur har result ke liye ek widget chunte hain.

**Do faisle jo is file ka dhaancha tay karte hain:**

1. **Sub-questions LLM banata hai, widgets nahi.** Sawaal me judgement hai — "salary
   ke baare me kya poochha jaana chahiye" ka koi ek jawab nahi. Widget me judgement
   nahi hai: ek row ek column ka matlab KPI hai, char categories ka matlab bar hai.
   Wo data ki **shakl** se tay hota hai, aur uske liye ek aur LLM call lagana ek
   deterministic faisle ko probabilistic bana dena hai.

2. **Har sub-question poore agent se guzarta hai**, kisi chhote raaste se nahi.
   Matlab retry loop, output guard, approval gate — sab waise ke waise lagte hain.
   Agar dashboard ka apna alag SQL path hota, to woh sab bypass ho jaata, aur
   system ke sabse kam dekhe jaane wale raaste par sabse kam safety hoti.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.data_access import get_schema_description
from app.graph import _llm, run_agent

# Ek dashboard me kitne widgets. Har widget ek poora agent run hai (1-2 LLM calls,
# retry pe aur zyada), aur free tier ~15 requests/minute deta hai. Chaar pe ek
# dashboard ~6-9 calls leta hai — jo is quota me theek baithta hai. Zyada rakhne
# se pehla hi dashboard poora quota kha jaata.
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
    """Request ko sub-questions me todta hai.

    JSON array maangte hain aur defensively parse karte hain — model kabhi fence
    ya ek line ki bhoomika laga deta hai. Parse fail ho to khaali list, jise
    caller ek saaf message me badal deta hai; ek adhoora dashboard dikhane se
    behtar hai saaf keh dena ki plan nahi ban paaya.
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


# Measure names jo **jodne layak** hain — inka total ek matlab rakhta hai.
_ADDITIVE = ("count", "total", "sum", "headcount", "num", "spend", "budget", "payroll")

# Measure names jo jodne layak **nahi** hain. Averages, rates aur percentages ka
# yog bemaani hota hai.
_NON_ADDITIVE = ("avg", "average", "mean", "median", "rate", "percent", "pct", "ratio")


def _is_part_of_whole(column: str) -> bool:
    """Kya is measure ka total matlab rakhta hai — matlab donut jaayaz hai.

    **Ye check pehle nahi tha, aur pehle hi asli dashboard me bug nikal aaya:**
    "average salary by department" ko donut mil gaya. Donut kehta hai "ye hisse
    ek poore ke hain", par averages jodte nahi — chaar departments ke average
    salary ka yog kisi cheez ko represent nahi karta. Us chart ne data ke baare
    me ek baat kahi jo sach nahi thi.

    Naam se andaza lagana perfect nahi hai (`salary` akela ambiguous hai), par
    galat hone par nateeja bar chart hai — jo hamesha imaandaar rehta hai. Donut
    tabhi milta hai jab wo saaf taur par jodne layak ho.
    """
    lowered = column.lower()
    if any(word in lowered for word in _NON_ADDITIVE):
        return False
    return any(word in lowered for word in _ADDITIVE)


def choose_widget(rows: list[dict]) -> str:
    """Result set ki shakl se widget chunta hai. Koi LLM nahi — ye judgement nahi hai.

    Rules, is order me:

    - ek row, ek column                       -> `kpi`   (ek number ko chart me dikhana decoration hai)
    - do column, doosra jodne-layak number, <= 6 rows -> `donut` (ek poore ke hisse)
    - do column, doosra number                -> `bar`   (categories ki tulna)
    - baaki sab                               -> `table` (jo plot nahi hota use plot mat karo)

    Donut ke liye 6 ka cap: usse zyada slices par arc lambai se padhna band ho
    jaata hai aur legend hi chart ban jaata hai — wahan bar imaandaar hai.
    """
    if not rows:
        return "empty"

    columns = list(rows[0].keys())

    if len(rows) == 1 and len(columns) == 1:
        return "kpi"

    if len(columns) == 2:
        second = rows[0][columns[1]]
        # `bool` Python me `int` ka subclass hai — bina is check ke ek true/false
        # column magnitude ki tarah plot ho jaata.
        numeric = isinstance(second, (int, float)) and not isinstance(second, bool)
        if numeric:
            if len(rows) <= 6 and _is_part_of_whole(columns[1]):
                return "donut"
            return "bar"

    return "table"


def build_dashboard(request: str, thread_id: Optional[str] = None) -> dict:
    """Ek request se dashboard banata hai.

    `thread_id` seedha agent ko pass hota hai, to dashboard ke sawaal usi
    conversation me darj hote hain — baad me "us dashboard me Engineering ka
    number kya tha?" poochna kaam karta hai.
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

        # Approval gate ya failure — widget banane ko kuch nahi. Isko chhodne ke
        # bajaye record karte hain: ek dashboard jisme chupchaap ek kam widget ho,
        # wo ek dashboard se bura hai jo bata de ki ek sawaal ka jawab nahi mila.
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
    """Request ko ek chhote title me badalta hai — bina LLM call ke.

    Ek aur model call sirf heading ke liye lagana quota ka bura istemaal hai, aur
    heading galat hone ka nuksaan bhi utna hi kam hai. Prefixes hata kar pehla
    hissa le lete hain.
    """
    text = re.sub(
        # `me` ko alag optional group me rakha hai: "show me ..." aur "give me ..."
        # dono aate hain, aur use verb ke saath jodne se ek chhoot jaata hai.
        r"^(create|make|build|show|give|display)\s+(me\s+)?(a|an|the)?\s*"
        r"(dashboard|report|overview)?\s*(showing|for|of|with|about)?\s*",
        "",
        request.strip(),
        flags=re.IGNORECASE,
    )
    text = text.split(".")[0].strip(" ,") or request.strip()
    return (text[:1].upper() + text[1:])[:70]
