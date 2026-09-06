import os
import re
from typing import List, Optional, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph

from app.checkpointer import get_checkpointer
from app.db import get_schema_description, run_sql, run_write

# Env se override ho sakta hai — eval harness isko 0 set karke measure karta hai
# ki self-healing loop ke bina accuracy kitni girti hai.
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))

# Env se override ho sakta hai — model versions deprecate hote rehte hain,
# aur eval me alag models compare karne ke liye bhi kaam aata hai.
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
# mode me chalana aur. Ye seedha usi sabak se aaya hai jo `synthesize` ke
# read-only prompt me likha hai — action guard karna aur us action ki **report**
# guard karna do alag zimmedariyaan hain.
ALLOW_WRITES = os.environ.get("ALLOW_WRITES", "").lower() in ("1", "true", "yes")


# Ek conversation me kitne pichhle turns prompt me bhejne hain. Poori history
# bhejna do tarah se mehnga hai — tokens, aur dhyaan: bees turn purani baat
# aksar current sawaal se koi rishta nahi rakhti, par model use context maan ke
# usme se entities utha leta hai. Teen follow-up chain ke liye kaafi hai.
HISTORY_TURNS_IN_PROMPT = int(os.environ.get("HISTORY_TURNS_IN_PROMPT", "3"))


class ConversationTurn(TypedDict):
    question: str
    sql_query: str
    answer: str


class AgentState(TypedDict):
    # --- per-turn: har naye sawaal pe reset hote hain -----------------------
    question: str
    sql_query: str
    query_result: str
    error: str
    retry_count: int
    final_answer: str
    logs: List[str]

    hitl_enabled: bool
    """Is turn me approval gate available hai ya nahi.

    Interrupt ke liye checkpointer chahiye, to HITL sirf `thread_id` wale path pe
    milta hai. Ye flag `generate_sql` tak wo baat pahunchata hai, kyunki gate hone
    ya na hone se ye badal jaata hai ki model ko write likhne di jaaye ya nahi.
    """

    approval_status: str
    """HITL gate ki haalat: `""` | `"pending"` | `"approved"` | `"rejected"`.

    Per-turn hai, per-conversation nahi — ek turn ki approval agle turn ki write
    ko authorize nahi karti. Wahi bug hoti jo `retry_count` ke saath hoti, bas
    isme nateeja data change hota.
    """

    # --- per-conversation: turns ke beech zinda rehte hain ------------------
    history: List[ConversationTurn]
    """Pichhle turns, checkpointer ke through carry hote hue.

    **Checkpointer aa jaane ke baad ye batana zaroori ho jaata hai ki kaunsi
    field kis scope ki hai.** Bina memory ke har invocation khaali state se
    shuru hoti thi, to sawaal uthta hi nahi tha. Ab state turns ke beech survive
    karti hai — aur agar `retry_count` ya `logs` bhi survive kar jaayein to
    pichhle turn ki do retries agle turn ko turant "give up" pe dhakel dengi,
    aur trace me pichhle sawaal ki lines dikhengi.

    Isliye `run_agent` har naye sawaal pe upar wali saari fields explicitly
    reset karta hai, aur `history` ko chhodta hai. Yahi ek line ye tay karti hai
    ki memory feature hai ya bug.

    Reducer (`Annotated[..., operator.add]`) jaan-boojh ke nahi lagaya: nodes
    `{**state, ...}` return karte hain, to har node poori history wapas bhejta
    hai — additive reducer use har baar dobara jod deta aur history exponentially
    badhti. Overwrite semantics ke saath sirf `synthesize_and_validate` isme ek
    turn add karta hai, ek hi jagah, ek hi baar.
    """


def _llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
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

    recent = history[-HISTORY_TURNS_IN_PROMPT:]
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
    return any(keyword in sql_query.upper() for keyword in BLOCKED_KEYWORDS)


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
                "retry_count": MAX_RETRIES,
                "logs": logs,
            }

        try:
            affected = run_write(sql_query, commit=ALLOW_WRITES)
        except Exception as exc:
            logs.append(f"Execution failed: {exc}")
            return {
                **state,
                "error": str(exc),
                "retry_count": state.get("retry_count", 0) + 1,
                "logs": logs,
            }

        if ALLOW_WRITES:
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
        logs.append(f"Execution succeeded, {len(rows)} row(s) returned.")
        return {**state, "query_result": str(rows), "error": "", "logs": logs}
    except Exception as exc:
        logs.append(f"Execution failed: {exc}")
        return {
            **state,
            "error": str(exc),
            "retry_count": state.get("retry_count", 0) + 1,
            "logs": logs,
        }


def should_retry(state: AgentState) -> str:
    if state.get("error") and state.get("retry_count", 0) < MAX_RETRIES:
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
            f"after {MAX_RETRIES} attempts. Last error: {state['error']}"
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
                        if ALLOW_WRITES
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
    return {
        **state,
        "final_answer": response.content,
        "logs": logs,
        "history": _append_turn(state, response.content),
    }


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("await_approval", await_approval)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("synthesize_and_validate", synthesize_and_validate)

    graph.set_entry_point("generate_sql")

    # Destructive query approval gate se hoke jaati hai, baaki seedha execute.
    graph.add_conditional_edges(
        "generate_sql",
        needs_approval,
        {"approval": "await_approval", "execute": "execute_sql"},
    )
    graph.add_conditional_edges(
        "await_approval",
        after_approval,
        {"execute": "execute_sql", "rejected": "synthesize_and_validate"},
    )
    graph.add_conditional_edges(
        "execute_sql",
        should_retry,
        {
            "retry": "generate_sql",
            "give_up": "synthesize_and_validate",
            "success": "synthesize_and_validate",
        },
    )
    graph.add_edge("synthesize_and_validate", END)

    # **Interrupt sirf checkpointer ke saath.** LangGraph ko pause karke baad me
    # resume karne ke liye state kahin save karni padti hai — bina checkpointer
    # ke `interrupt_before` ka koi matlab nahi. Isliye stateless graph purane
    # hard block pe chalta hai, aur HITL sirf `thread_id` wale path pe milta hai.
    # Ye Phase 4 ke Phase 3 se pehle aane ka seedha nateeja hai, ittefaq nahi.
    if checkpointer is not None:
        return graph.compile(
            checkpointer=checkpointer, interrupt_before=["await_approval"]
        )
    return graph.compile()


# Compiled graphs cache. Pehle har request `build_graph()` chalati thi, jo bina
# checkpointer ke sirf fizool tha — ab galat bhi hota, kyunki checkpointer ke
# peeche connection pool hai aur har request pe naya pool kholna leak hai.
_graphs: dict = {}


def _get_graph(checkpointer=None):
    key = "memory" if checkpointer is not None else "stateless"
    if key not in _graphs:
        _graphs[key] = build_graph(checkpointer)
    return _graphs[key]


def run_agent(question: str, thread_id: Optional[str] = None) -> AgentState:
    """Ek sawaal chalao. `thread_id` do to wo conversation continue hoti hai.

    `thread_id` ke bina behaviour bilkul pehle jaisa hai — stateless, koi memory
    nahi. Eval harness aur tests isi path pe chalte hain, aur yahi unke liye sahi
    hai: har eval question independent hona chahiye, warna pehle sawaal ka jawab
    agle ka score badal dega.
    """
    checkpointer = get_checkpointer() if thread_id else None
    app = _get_graph(checkpointer)

    # **Har naye sawaal pe per-turn fields explicitly reset.** Checkpointer ke
    # saath ye zaroori hai: LangGraph is dict ko checkpointed state ke upar merge
    # karta hai, to jo key yahan nahi hai wo pichhle turn se aage carry hoti hai.
    # `history` jaan-boojh ke chhodi hai — usi ko carry hona chahiye. Baaki sab
    # reset hona chahiye, warna pichhle turn ki retries agle turn ko turant
    # "give up" pe dhakel dengi aur trace me purane sawaal ki lines dikhengi.
    turn_input: dict = {
        "question": question,
        "sql_query": "",
        "query_result": "",
        "error": "",
        "retry_count": 0,
        "final_answer": "",
        "logs": [],
        # Pichhle turn ki approval is turn ki write ko authorize na kar de.
        "approval_status": "",
        # Gate tabhi hai jab checkpointer hai — interrupt ko state save karne ki
        # jagah chahiye. Isi se tay hota hai ki model write likh sakta hai ya nahi.
        "hitl_enabled": checkpointer is not None,
    }

    if checkpointer is None:
        turn_input["history"] = []
        return app.invoke(turn_input)

    config = {"configurable": {"thread_id": thread_id}}
    result = app.invoke(turn_input, config=config)

    # Agar graph approval gate pe ruka hai to `invoke` us waqt ki state lauta
    # deta hai, `final_answer` khaali. Ise "poora ho gaya" maan lena sabse
    # gumraah karne wala outcome hota: caller ko khaali jawab milta aur pata
    # bhi nahi chalta ki system uske faisle ka intezaar kar raha hai.
    if _is_awaiting_approval(app, config):
        return {**result, "approval_status": "pending"}
    return result


def _is_awaiting_approval(app, config) -> bool:
    """Graph approval node se pehle ruka hua hai ya nahi.

    `state.next` batata hai ki agla kaun sa node chalega. Interrupt ke baad wahan
    `await_approval` hota hai — matlab graph gate pe khada hai, andar nahi gaya.
    """
    try:
        snapshot = app.get_state(config)
    except Exception:  # noqa: BLE001 — checkpointer read fail; treat as not paused
        return False
    return "await_approval" in (snapshot.next or ())


def resume_agent(thread_id: str, approved: bool) -> Optional[AgentState]:
    """Ruki hui conversation ko insaan ke faisle ke saath aage badhata hai.

    `None` deta hai agar ye thread approval ka intezaar hi nahi kar raha —
    caller ke liye ye 409 hai, 500 nahi: request galat nahi hai, bas is waqt
    lagoo nahi hoti (do baar approve dabana, ya purana tab).
    """
    checkpointer = get_checkpointer()
    if checkpointer is None:
        return None

    app = _get_graph(checkpointer)
    config = {"configurable": {"thread_id": thread_id}}

    if not _is_awaiting_approval(app, config):
        return None

    # Faisla state me likho, phir bina naye input ke resume karo. `None` ka matlab
    # hai "jahan ruke the wahin se chalao" — naya input dene se turn dobara shuru
    # ho jaata aur ek aur LLM call lag jaati.
    app.update_state(
        config, {"approval_status": "approved" if approved else "rejected"}
    )
    return app.invoke(None, config=config)
