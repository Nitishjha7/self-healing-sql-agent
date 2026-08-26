# Self-Healing Data Query Agent: Technical Specification & Implementation Guide

This document provides a comprehensive technical specification, architecture design, and end-to-end implementation details for the Self-Healing Data Query Agent. Built using LangGraph, LangChain, Guardrails AI, FastAPI, PostgreSQL, and React, this system translates natural language questions into structured SQL queries, autonomously detects syntax/schema errors, executes self-healing reflection loops, and validates outputs against security and content policies.

## 1. Executive Summary & Core Objectives

Traditional Text-to-SQL systems often fail when encountering complex schema joins, dialect differences, or ambiguous natural language queries. Without autonomous feedback, a single database syntax error results in a broken user experience. The Self-Healing Data Query Agent solves this by introducing cyclical graph-based execution:

- **Cyclic State Graphs**: Utilizes LangGraph to implement stateful retry and self-healing loops upon SQL runtime failures.
- **Safety & Policy Guardrails**: Integrates Guardrails AI to sanitize model responses, preventing schema leakage and offensive output generation.
- **Full-Stack Decoupling**: Exposes the agentic state machine via a modular FastAPI REST interface paired with a reactive React frontend and Docker orchestration.

## 2. System Architecture & Component Breakdown

The system operates across three primary layers: UI Client, Orchestration/Backend Layer, and the Data Persistence Layer.

| Component | Technology | Primary Role |
|---|---|---|
| Agent Workflow | LangGraph (Python) | State machine management, node transitions, and conditional self-correction branching. |
| LLM Inference | LangChain / Groq (Llama 3.3 70B) | SQL generation, error reflection, and natural language synthesis. |
| Output Validation | Guardrails AI | Validates synthesized responses for toxic language, hallucination, and schema integrity. |
| API Backend | FastAPI + Uvicorn | REST endpoints serving agent execution steps, trace logs, and responses. |
| Data Store | SQLite3 | Target relational database for executing generated queries. |
| Frontend UI | React + Vite | Chat interface providing real-time visibility into internal agent thought logs and SQL queries. |
| Containerization | Docker & Docker Compose | Unified multi-container deployment with Nginx reverse proxy. |

## 3. LangGraph State Machine & Self-Healing Logic

The agent utilizes a structured `AgentState` schema to carry context across nodes. When query execution fails, execution jumps back to the generation node with detailed database feedback.

```
+-------------------+
|    User Prompt    |
+-------------------+
          |
          v
+-------------------+
|   generate_sql    | <---------------------+
+-------------------+                       |
          |                                 | (If SQL error & retry < 3)
          v                                 |
+-------------------+                       |
|    execute_sql    | -- [Conditional Edge] +
+-------------------+
          | (On Success)
          v
+------------------------+
| synthesize_and_validate|
+------------------------+
          |
          v
+-------------------+
|    Final Output   |
+-------------------+
```

### State Definition Specification

```python
class AgentState(TypedDict):
    question: str       # Original natural language question
    sql_query: str      # Generated SQL statement
    query_result: str   # Raw database output
    error: str          # Exception message (if query execution failed)
    retry_count: int    # Current retry iteration (Max limit: 3)
    final_answer: str   # Validated natural language response
    logs: List[str]     # Step-by-step trace logs for UI visibility
```

## 4. Database Schema & Sample Dataset

The agent connects to a local relational SQLite database representing an enterprise employee directory.

| Column Name | Data Type | Constraints | Description |
|---|---|---|---|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | Unique identifier for employee record. |
| name | TEXT | NOT NULL | Full name of the employee. |
| department | TEXT | NOT NULL | Assigned department (e.g., Engineering, Marketing, HR). |
| salary | INTEGER | CHECK(salary > 0) | Annual base compensation. |
| role | TEXT | NOT NULL | Job title / functional role. |

## 5. End-to-End Execution Flow & Lifecycle

1. **Query Ingestion**: The user enters a question in the React interface (e.g., "Who earns more than 80000 in Engineering?").
2. **SQL Construction Node**: The LangGraph agent inspects the database schema and generates the initial SQL query.
3. **Execution & Inspection**: The query is run against SQLite.
   - If execution succeeds: Rows are passed forward to the synthesizer.
   - If a syntax/schema error occurs: Error traceback is captured into the state, `retry_count` is incremented, and the agent re-enters the generation node with error context.
4. **Guardrails Verification**: The final synthesized answer is parsed through Guardrails AI to verify safety and prevent sensitive data leakage.
5. **Trace Delivery**: The API returns the answer along with step logs and the executed SQL query for client-side visualization.

## 6. Docker Containerization & Deployment Model

The application is fully containerized using a multi-service Docker Compose architecture:

- **Backend Service**: Lightweight Python 3.11-slim container running FastAPI with persistent SQLite volume mounting.
- **Frontend Service**: Multi-stage Node.js build served via high-performance Nginx with built-in `/api/` reverse proxy routing.
- **Single-Command Orchestration**: Entire stack spins up via `docker compose up --build` with environment variable injection.

## 7. Future Extensions & Scaling Roadmap

| Phase | Enhancement Feature | Technical Impact |
|---|---|---|
| Phase 2 | Model Context Protocol (MCP) | Replace direct SQLite driver with standard SQLite MCP Server over stdio. |
| Phase 3 | Human-in-the-Loop (HITL) | Introduce approval pauses before executing destructive queries (UPDATE/DELETE). |
| Phase 4 | Postgres Checkpointer | Enable cross-session conversation memory and multi-tenant isolation. |
