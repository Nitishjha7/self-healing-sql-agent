import os
import re
from typing import List, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph

from app.db import get_schema_description, run_sql

MAX_RETRIES = 3

BLOCKED_KEYWORDS = ("DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE")


class AgentState(TypedDict):
    question: str
    sql_query: str
    query_result: str
    error: str
    retry_count: int
    final_answer: str
    logs: List[str]


def _llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        google_api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0,
    )


def _extract_sql(text: str) -> str:
    """LLM response se sirf SQL nikaalta hai (agar ```sql fenced block ho toh usme se)."""
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    sql = match.group(1) if match else text
    return sql.strip().rstrip(";")


def generate_sql(state: AgentState) -> AgentState:
    schema = get_schema_description()
    logs = state.get("logs", [])

    if state.get("error"):
        prompt = (
            f"Schema:\n{schema}\n\n"
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
            f"Question: {state['question']}\n\n"
            "Write a single PostgreSQL SELECT query that answers this question. "
            "Return ONLY the SQL query, no explanation."
        )
        logs.append("Generating initial SQL query.")

    response = _llm().invoke(
        [
            SystemMessage(content="You are an expert PostgreSQL query writer. Only ever write SELECT queries."),
            HumanMessage(content=prompt),
        ]
    )
    sql_query = _extract_sql(response.content)
    logs.append(f"Generated SQL: {sql_query}")

    return {**state, "sql_query": sql_query, "logs": logs}


def execute_sql(state: AgentState) -> AgentState:
    logs = state.get("logs", [])
    sql_query = state["sql_query"]

    if any(keyword in sql_query.upper() for keyword in BLOCKED_KEYWORDS):
        logs.append("Blocked: query contains a destructive/write keyword.")
        return {
            **state,
            "error": "Only read-only SELECT queries are allowed.",
            "retry_count": MAX_RETRIES,
            "logs": logs,
        }

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


def synthesize_and_validate(state: AgentState) -> AgentState:
    logs = state.get("logs", [])

    if state.get("error"):
        answer = (
            "Sorry, I couldn't answer that question — the query kept failing "
            f"after {MAX_RETRIES} attempts. Last error: {state['error']}"
        )
        logs.append("Giving up after max retries.")
        return {**state, "final_answer": answer, "logs": logs}

    response = _llm().invoke(
        [
            SystemMessage(
                content=(
                    "You turn SQL query results into a short, natural-language answer. "
                    "Never reveal raw table/column names or internal schema details. "
                    "Never include employee salary figures for more than one person unless explicitly asked to compare."
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
    return {**state, "final_answer": response.content, "logs": logs}


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("synthesize_and_validate", synthesize_and_validate)

    graph.set_entry_point("generate_sql")
    graph.add_edge("generate_sql", "execute_sql")
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

    return graph.compile()


def run_agent(question: str) -> AgentState:
    app = build_graph()
    initial_state: AgentState = {
        "question": question,
        "sql_query": "",
        "query_result": "",
        "error": "",
        "retry_count": 0,
        "final_answer": "",
        "logs": [],
    }
    return app.invoke(initial_state)
