"""The graph's nodes, and the predicates that route between them.

This is where the agent's behaviour lives: how it writes SQL, what it does when
the database refuses it, when it stops to ask a human, and how it turns rows back
into a sentence. The wiring that connects these is in `graph.py`; the shapes they
read and write are in `state.py`; the settings they obey are in `config.py`.

Settings are read as `config.MAX_RETRIES` rather than imported by value, because
the eval harness and the tests patch them at runtime — a `from config import
MAX_RETRIES` would bind the number once at import and quietly ignore the patch.
"""

import re
from typing import List

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app import config

# Data access ek layer ke peeche hai (direct driver ya MCP tools) — nodes ko
# farak nahi padta kaunsa chal raha hai. Dekho app/data_access.py.
from app.data_access import get_schema_description, run_sql, run_write
from app.data_access import mode as data_access_mode
from app.state import AgentState, ConversationTurn, _serializable
from app.validators import validate_answer


def _llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=config.GEMINI_MODEL,
        google_api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0,
    )


def _extract_sql(text: str) -> str:
    """LLM response se sirf SQL nikaalta hai (agar ```sql fenced block ho toh usme se)."""
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    sql = match.group(1) if match else text
    return sql.strip().rstrip(";")


def _format_history(history: List[ConversationTurn]) -> str:
    """Pichhle turns ko prompt ke ek block me badalta hai.

    **Sirf checkpointer se follow-up kaam nahi karte.** Checkpointer state ko
    durable banata hai; par jab tak wo state prompt me nahi jaati, model ke liye
    "unme se kitne Bangalore me hain?" ek adhoora vaakya hai. Memory = durable
    state **+** us state ka prompt me pahunchna. Dono chahiye.

    Har turn ka SQL bhi bhejte hain, sirf answer nahi — agar pichhla sawaal
    "highest average salary wala department" tha, to us SQL me `GROUP BY d.name
    ORDER BY AVG(e.salary) DESC LIMIT 1` likha hai, jo model ko exactly batata
    hai ki "unme se" ka referent kya hai. Angrezi answer se ye kam saaf hota hai.
    """
    if not history:
        return ""

    recent = history[-config.HISTORY_TURNS_IN_PROMPT:]
    lines = ["Earlier in this conversation:"]
    for i, turn in enumerate(recent, 1):
        lines.append(f"{i}. User asked: {turn['question']}")
        if turn.get("sql_query"):
            lines.append(f"   SQL used: {turn['sql_query']}")
        if turn.get("answer"):
            lines.append(f"   Answer given: {turn['answer']}")
    lines.append(
        "\nIf the new question refers back to those results using words like "
        "'them', 'those', 'that department' or 'it', resolve the reference from "
        "the conversation above and write a self-contained query."
    )
    return "\n".join(lines) + "\n\n"


def generate_sql(state: AgentState) -> AgentState:
    schema = get_schema_description()
    logs = state.get("logs", [])
    history_block = _format_history(state.get("history") or [])

    if state.get("error"):
        prompt = (
            f"Schema:\n{schema}\n\n"
            f"{history_block}"
            f"Question: {state['question']}\n\n"
            f"Previous SQL attempt:\n{state['sql_query']}\n\n"
            f"That query failed with this error:\n{state['error']}\n\n"
            "Fix the SQL query so it runs correctly against this schema. "
            "Return ONLY the corrected SQL query, no explanation."
        )
        logs.append(f"Retry {state['retry_count']}: regenerating SQL after error: {state['error']}")
    else:
        prompt = (
            f"Schema:\n{schema}\n\n"
            f"{history_block}"
            f"Question: {state['question']}\n\n"
            "Write a single PostgreSQL SELECT query that answers this question. "
            "Join across tables where the question needs data from more than one. "
            "Return ONLY the SQL query, no explanation."
        )
        if history_block:
            logs.append(
                f"Generating initial SQL query (with {len(state.get('history') or [])} "
                "earlier turn(s) as context)."
            )
        else:
            logs.append("Generating initial SQL query.")

    # **Ye constraint gate ke hisaab se badalti hai, aur badalni chahiye.**
    # "Sirf SELECT likho" isliye tha kyunki koi approval gate nahi tha — model ki
    # nikali hui koi bhi write seedha database tak jaati. Ab HITL wale path pe
    # insaan har write ko dekhta hai, to yahan mana karte rehna poore Phase 3 ko
    # dead code bana deta: gate kabhi trigger hi nahi hota kyunki destructive SQL
    # kabhi banti hi nahi. Stateless path pe gate hai hi nahi, isliye wahan purani
    # sakht line hi sahi hai.
    system_prompt = (
        "You are an expert PostgreSQL query writer. Write SELECT queries. "
        "If the user explicitly asks to modify data, write the appropriate "
        "INSERT/UPDATE/DELETE statement — a human reviews and approves every "
        "such statement before it runs. Never modify data the user did not ask "
        "to modify."
        if state.get("hitl_enabled")
        else "You are an expert PostgreSQL query writer. Only ever write SELECT queries."
    )

    response = _llm().invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt),
        ]
    )
    sql_query = _extract_sql(response.content)
    logs.append(f"Generated SQL: {sql_query}")

    return {**state, "sql_query": sql_query, "logs": logs}


def is_destructive(sql_query: str) -> bool:
    """SQL me koi write/DDL keyword hai ya nahi.

    Substring match hai, matlab conservative — string literal me aaya "updated"
    bhi ise trigger kar dega. Ye jaan-boojh ke hai: false positive ka anjaam ek
    fizool approval prompt hai, false negative ka anjaam bina puche data badal
    jaana. Asli production answer database-level read-only role hai, jise prompt
    injection se bypass nahi kiya ja sakta — ye uski jagah nahi leta.
    """
    return any(keyword in sql_query.upper() for keyword in config.BLOCKED_KEYWORDS)


def needs_approval(state: AgentState) -> str:
    """`generate_sql` ke baad ka conditional edge: approval chahiye ya seedha chalao."""
    if is_destructive(state.get("sql_query", "")):
        return "approval"
    return "execute"


def await_approval(state: AgentState) -> AgentState:
    """HITL gate. Graph is node se **pehle** rukta hai (`interrupt_before`).

    Node khud tab chalta hai jab conversation resume hoti hai, matlab tab tak
    `approval_status` insaan ke faisle se bhar chuka hota hai. Isliye ye node
    khud kuch poochta nahi — wo faisla record karta hai, taaki trace me dikhe ki
    ruka kis wajah se aur aage badha kis faisle pe.

    **Ye alag node isliye hai** ki is LangGraph version me dynamic `interrupt()`
    nahi hai — sirf static `interrupt_before=[...]`. `execute_sql` pe seedha
    interrupt lagate to har query ruk jaati, sirf destructive nahi. Ek dedicated
    node banane se pause **conditional** ho jaata hai: routing tay karti hai ki
    is turn me gate se guzarna hai ya nahi.
    """
    logs = state.get("logs", [])
    decision = state.get("approval_status", "")

    if decision == "approved":
        logs.append("Human approved the write. Proceeding.")
    elif decision == "rejected":
        logs.append("Human rejected the write. Nothing was executed.")
    else:
        # Yahan pahunchna matlab resume bina faisle ke hua. Chup-chaap chalne
        # dena sabse kharaab option hai — gate ka poora matlab hi khatam.
        logs.append("Resumed without a decision — treating as rejected.")
        decision = "rejected"

    return {**state, "approval_status": decision, "logs": logs}


def after_approval(state: AgentState) -> str:
    return "execute" if state.get("approval_status") == "approved" else "rejected"


def execute_sql(state: AgentState) -> AgentState:
    logs = state.get("logs", [])
    sql_query = state["sql_query"]

    if is_destructive(sql_query):
        # Approval mile bina yahan pahunchna sirf stateless mode me hota hai,
        # jahan checkpointer nahi hai to interrupt bhi possible nahi. Wahan
        # purana hard block hi sahi behaviour hai — approval prompt dikhana
        # jise honour hi nahi kiya ja sakta, uska koi matlab nahi.
        if state.get("approval_status") != "approved":
            logs.append("Blocked: query contains a destructive/write keyword.")
            return {
                **state,
                "error": "Only read-only SELECT queries are allowed.",
                "retry_count": config.MAX_RETRIES,
                "logs": logs,
            }

        try:
            affected = run_write(sql_query, commit=config.ALLOW_WRITES)
        except Exception as exc:
            logs.append(f"Execution failed: {exc}")
            return {
                **state,
                "error": str(exc),
                "retry_count": state.get("retry_count", 0) + 1,
                "logs": logs,
            }

        if config.ALLOW_WRITES:
            logs.append(f"Write committed, {affected} row(s) affected.")
            result = f"Write committed. {affected} row(s) affected."
        else:
            logs.append(
                f"Write executed and rolled back (ALLOW_WRITES is off), "
                f"{affected} row(s) would have been affected."
            )
            result = (
                f"The statement ran against the database and was then rolled back "
                f"because this deployment does not permit writes. It would have "
                f"affected {affected} row(s). Nothing was actually changed."
            )
        return {**state, "query_result": result, "error": "", "logs": logs}

    try:
        rows = run_sql(sql_query)
        # Data access mode trace me dikhta hai. MCP on karke bhi kuch alag na
        # dikhna matlab ye pata hi na chalna ki wo actually chala ya chup-chaap
        # direct driver pe gir gaya.
        via = " via MCP tool" if data_access_mode() == "mcp" else ""
        logs.append(f"Execution succeeded{via}, {len(rows)} row(s) returned.")
        return {
            **state,
            "query_result": str(rows),
            # UI ke liye rows structured shakl me bhi, taaki wo table dikha sake.
            # Cap isliye ki ye checkpointer me likhi jaati hain aur har response
            # me jaati hain — ek "SELECT * FROM employees" jaisa sawaal poori
            # table ko conversation state me daal deta.
            "result_rows": _serializable(rows[:config.MAX_RESULT_ROWS]),
            "row_count": len(rows),
            "error": "",
            "logs": logs,
        }
    except Exception as exc:
        logs.append(f"Execution failed: {exc}")
        return {
            **state,
            "error": str(exc),
            "retry_count": state.get("retry_count", 0) + 1,
            "logs": logs,
        }


def should_retry(state: AgentState) -> str:
    if state.get("error") and state.get("retry_count", 0) < config.MAX_RETRIES:
        return "retry"
    if state.get("error"):
        return "give_up"
    return "success"


def _append_turn(state: AgentState, answer: str) -> List[ConversationTurn]:
    """History me is turn ka record jodta hai.

    Sirf yahi ek function history likhta hai — `synthesize_and_validate` graph ka
    aakhri node hai, to yahan tak pahunchne ka matlab hai turn poora ho chuka.
    Beech ke nodes me append karna retry loop me ek hi turn ko teen baar likh
    deta (`generate_sql` retry pe dobara chalta hai).
    """
    return (state.get("history") or []) + [
        {
            "question": state["question"],
            "sql_query": state.get("sql_query", ""),
            "answer": answer,
        }
    ]


def synthesize_and_validate(state: AgentState) -> AgentState:
    logs = state.get("logs", [])

    if state.get("approval_status") == "rejected":
        # Rejection ko LLM se nahi likhwate. Ye ek policy outcome hai, ek fixed
        # fact — usko generate karwana matlab model ko ye mauka dena ki wo use
        # narrate karte hue kuch aur bol de. Yahi galti pehle "removed from the
        # HR department" wale jhooth me nikli thi.
        answer = (
            "That request was not approved, so nothing was run against the "
            "database. Nothing has been changed."
        )
        return {
            **state,
            "final_answer": answer,
            "logs": logs,
            "history": _append_turn(state, answer),
        }

    if state.get("error"):
        answer = (
            "Sorry, I couldn't answer that question — the query kept failing "
            f"after {config.MAX_RETRIES} attempts. Last error: {state['error']}"
        )
        logs.append("Giving up after max retries.")
        # Failed turn bhi history me jaata hai. Chhodne se agla follow-up chup-chaap
        # ek aise turn ko refer karta jo kabhi hua hi nahi — aur "usme se kitne"
        # ka jawab pichhle *safal* turn se aata, jo galat ban jaata.
        return {
            **state,
            "final_answer": answer,
            "logs": logs,
            "history": _append_turn(state, answer),
        }

    response = _llm().invoke(
        [
            SystemMessage(
                content=(
                    "You turn SQL query results into a short, natural-language answer. "
                    "Never reveal raw table/column names or internal schema details. "
                    "Never include employee salary figures for more than one person unless explicitly asked to compare. "
                    # Without this the synthesizer reads a question like "delete all
                    # employees from HR", sees rows come back from the SELECT that
                    # actually ran, and reports the deletion as done. The data was
                    # never touched, but the user is told it was — a false
                    # confirmation is its own kind of harm, separate from the write
                    # the guard already prevented.
                    # Ye line ab conditional hai. Pehle hardcoded thi, aur ALLOW_WRITES
                    # aane ke baad wo galat direction me jhoot bulwane lagti: ek write
                    # jo sach me commit ho gaya, use "kuch nahi badla" batati. Guard
                    # dono taraf lagana padta hai — na jhoothi confirmation, na jhoothi
                    # tasalli.
                    + (
                        "This system runs write statements only after explicit human "
                        "approval. Report exactly what the result says happened — if it "
                        "says rows were affected, say so; if it says the statement was "
                        "rolled back, say that plainly and do not imply data changed."
                        if config.ALLOW_WRITES
                        else
                        "This system is STRICTLY READ-ONLY: it only ever runs SELECT queries and "
                        "never creates, updates or deletes anything. Never state or imply that data "
                        "was added, changed, removed or otherwise modified. If the question asked for "
                        "a modification, say plainly that you can only read data, then describe what "
                        "the query returned."
                    )
                )
            ),
            HumanMessage(
                content=(
                    f"Question: {state['question']}\n"
                    f"Query result: {state['query_result']}\n\n"
                    "Answer the question in one or two sentences."
                )
            ),
        ]
    )
    logs.append("Synthesized final answer.")

    # Prompt me schema-leakage ki jo baat likhi hai, wo yahan **enforce** hoti
    # hai. Prompt ek guzarish hai; ye check ek guarantee. Sirf model se keh dena
    # ki wo column naam na bole, aur maan lena ki usne suna — wo validation nahi,
    # ummeed hai.
    answer, flags = validate_answer(response.content)
    if flags:
        # Chup-chaap theek karke aage badhna galat hoga: leak hua tha ye baat
        # trace me dikhni chahiye, warna guard ka kaam karna aur guard ka kabhi
        # zaroorat na padna, dono ek jaise dikhte hain.
        logs.append(f"Output guard rewrote the answer: {', '.join(flags)}.")

    return {
        **state,
        "final_answer": answer,
        "guardrail_flags": flags,
        "logs": logs,
        "history": _append_turn(state, answer),
    }

