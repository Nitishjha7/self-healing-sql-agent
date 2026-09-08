"""The graph's nodes, and the predicates that route between them.

This is where the agent's behaviour lives: how it writes SQL, what it does when
the database refuses it, when it stops to ask a human, and how it turns rows back
into a sentence. The wiring that connects these is in `graph.py`; the shapes they
read and write are in `state.py`; the settings they obey are in `config.py`.

Settings are read as `config.MAX_RETRIES` rather than imported by value, because
the eval harness and the tests patch them at runtime — a `from config import
MAX_RETRIES` would bind the number once at import and quietly ignore the patch.
"""

import os
import re
from typing import List

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app import config

# Data access sits behind a layer (direct driver or MCP tools) — the nodes do
# not care which is running. See app/data_access.py.
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
    """Pull just the SQL out of an LLM response, unwrapping a ```sql fence if present."""
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    sql = match.group(1) if match else text
    return sql.strip().rstrip(";")


def _format_history(history: List[ConversationTurn]) -> str:
    """Render prior turns into a block for the prompt.

    **A checkpointer alone does not make follow-ups work.** It makes state
    durable, but until that state reaches the prompt, "how many of them are in
    Bangalore?" is an incomplete sentence to the model. Memory is durable state
    **plus** that state reaching the prompt. Both halves are required.

    Each turn's SQL goes in too, not just its answer. If the previous question
    was "which department has the highest average salary?", its SQL contains
    `GROUP BY d.name ORDER BY AVG(e.salary) DESC LIMIT 1`, which pins down what
    "them" refers to far more precisely than an English answer does.
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

    # **This constraint changes with the gate, and it has to.**
    # "Only write SELECT" existed *because* there was no approval gate: any write
    # the model produced would have gone straight to the database. On the HITL
    # path a human now reviews every write, so keeping the ban here would make the
    # whole of Phase 3 dead code — the gate would never fire, because destructive
    # SQL would never be generated. The stateless path has no gate, so the older,
    # stricter line is the right one there.
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
    """Whether the SQL contains any write or DDL keyword.

    Substring matching, so conservative — an "updated" inside a string literal
    will trigger it. That is deliberate: a false positive costs one unnecessary
    approval prompt, a false negative changes data nobody agreed to change. The
    real production answer is a database-level read-only role, which cannot be
    bypassed by prompt injection — this does not replace that.
    """
    return any(keyword in sql_query.upper() for keyword in config.BLOCKED_KEYWORDS)


def needs_approval(state: AgentState) -> str:
    """The conditional edge after `generate_sql`: gate it, or run it."""
    if is_destructive(state.get("sql_query", "")):
        return "approval"
    return "execute"


def await_approval(state: AgentState) -> AgentState:
    """The HITL gate. The graph stops **before** this node (`interrupt_before`).

    The node itself only runs once the conversation resumes, by which point
    `approval_status` already holds the human's decision. So it asks nothing —
    it records the decision, so the trace shows both what the run paused for and
    what it resumed on.

    **It is a separate node** because this LangGraph version has no dynamic
    `interrupt()`, only static `interrupt_before=[...]`. Putting that on
    `execute_sql` would pause *every* query, not just destructive ones. A
    dedicated node makes the pause **conditional**: routing decides whether this
    turn passes through the gate at all.
    """
    logs = state.get("logs", [])
    decision = state.get("approval_status", "")

    if decision == "approved":
        logs.append("Human approved the write. Proceeding.")
    elif decision == "rejected":
        logs.append("Human rejected the write. Nothing was executed.")
    else:
        # Reaching here means the resume arrived without a decision. Silently
        # proceeding is the worst option — it defeats the entire gate.
        logs.append("Resumed without a decision — treating as rejected.")
        decision = "rejected"

    return {**state, "approval_status": decision, "logs": logs}


def after_approval(state: AgentState) -> str:
    return "execute" if state.get("approval_status") == "approved" else "rejected"


def execute_sql(state: AgentState) -> AgentState:
    logs = state.get("logs", [])
    sql_query = state["sql_query"]

    if is_destructive(sql_query):
        # Arriving here unapproved only happens in stateless mode, where there is
        # no checkpointer and therefore no possible interrupt. The original hard
        # block is the right behaviour there: offering an approval prompt that
        # cannot be honoured is worse than refusing outright.
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
        # The data access mode shows in the trace. Turning MCP on and seeing
        # nothing change would leave no way to tell whether it actually ran or
        # silently fell back to the direct driver.
        via = " via MCP tool" if data_access_mode() == "mcp" else ""
        logs.append(f"Execution succeeded{via}, {len(rows)} row(s) returned.")
        return {
            **state,
            "query_result": str(rows),
            # Rows in structured form as well, so the UI can render a table. The
            # cap exists because these are written into the checkpointer and go
            # out in every response — an unbounded "SELECT * FROM employees" would
            # put the whole table into the conversation state.
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
    """Append a record of this turn to the history.

    This is the only function that writes history. `synthesize_and_validate` is
    the graph's last node, so reaching it means the turn is complete. Appending
    from an earlier node would record the same turn three times in a retry loop,
    since `generate_sql` runs again on each retry.
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
        # The rejection is not generated by the LLM. It is a policy outcome and a
        # fixed fact; generating it would give the model room to say something
        # else while narrating it. That is exactly the mistake behind the earlier
        # "removed from the HR department" falsehood.
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
        # A failed turn goes into history too. Dropping it would let the next
        # follow-up silently refer to a turn that never happened, and "how many of
        # them" would resolve against the previous *successful* turn instead.
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
                    # This line is conditional now. It used to be hardcoded, and once
                    # ALLOW_WRITES existed it started producing the opposite lie — a
                    # write that genuinely committed reported as "nothing changed".
                    # The guard has to work in both directions: no false confirmation,
                    # and no false reassurance.
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

    # What the prompt says about schema leakage is **enforced** here. The prompt
    # is a request; this check is the guarantee. Telling the model not to name
    # columns and assuming it complied is not validation — it is hope.
    answer, flags = validate_answer(response.content)
    if flags:
        # Fixing it silently would be wrong: that a leak happened has to be
        # visible in the trace, or "the guard did something" and "the guard was
        # never needed" look identical.
        logs.append(f"Output guard rewrote the answer: {', '.join(flags)}.")

    return {
        **state,
        "final_answer": answer,
        "guardrail_flags": flags,
        "logs": logs,
        "history": _append_turn(state, answer),
    }

