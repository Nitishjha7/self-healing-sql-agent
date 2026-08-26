# Code Notes — Kya Kis Liye Hai

Ye file har file/dependency ka **kaam aur reason** track karti hai, taaki baad me (ya interview me) yaad rahe ki har cheez kyun li gayi. Jaise-jaise code likha jayega, isko update karte rahenge.

---

## backend/requirements.txt

| Package | Kya kaam karta hai | Kyun liya |
|---|---|---|
| `fastapi` | REST API framework — endpoints define karne ke liye (`/query` jaisa endpoint jo agent ko trigger karega) | Fast, async-native, auto Swagger docs deta hai (`/docs` pe), FastAPI industry standard hai Python backend ke liye |
| `uvicorn[standard]` | ASGI server jo FastAPI app ko actually run karta hai | FastAPI khud server nahi hai, use run karne ke liye ek server chahiye — Uvicorn sabse common choice hai |
| `langgraph` | Graph-based agent orchestration library | Isi se `AgentState` state machine banayenge — nodes (`generate_sql`, `execute_sql`, `synthesize`) aur conditional edges (retry loop) define karne ke liye |
| `langchain` | LLM ke saath interact karne ka framework (prompts, chains, message formatting) | LangGraph ke nodes ke andar LLM calls isi se karenge |
| `langchain-google-genai` | LangChain ka Gemini-specific connector | Humne Gemini 2.0 Flash use karne ka decide kiya (free tier reliable hai) — isi package se Gemini ko LangChain me plug karte hain |
| `guardrails-ai` | Output validation library | Final answer ko check karne ke liye — schema leakage, toxic content, hallucination na ho isliye |
| `sqlalchemy` | Python se SQL database ke saath talk karne ka ORM/toolkit | PostgreSQL ke saath connection aur query execution ke liye — raw psycopg2 se zyada convenient hai |
| `psycopg2-binary` | PostgreSQL driver (actual low-level connector) | SQLAlchemy ko PostgreSQL se baat karne ke liye ye driver chahiye hota hai (SQLAlchemy khud driver nahi hai, wrapper hai) |
| `python-dotenv` | `.env` file se environment variables load karta hai | `DATABASE_URL`, `GOOGLE_API_KEY` jaise secrets ko code me hardcode karne ke bajaye `.env` se read karne ke liye |
| `pydantic` | Data validation / schema library | FastAPI request/response models define karne ke liye (jaise `QueryRequest { question: str }`) — FastAPI internally isi pe based hai |

---

---

## backend/app/db.py

**Kya karta hai:**
- SQLAlchemy `engine` banata hai jo `DATABASE_URL` env var se PostgreSQL se connect hota hai (default fallback localhost pe hai agar env var na mile).
- `init_db()` — `employees` table create karta hai (agar already nahi hai), aur agar table khaali hai toh 10 sample employee rows seed kar deta hai. Ye function container start hone par ek baar call hoga.
- `get_schema_description()` — schema ko plain text me return karta hai. Ye LLM ko prompt me dena hoga taaki wo columns/table naam sahi se jaan ke SQL banaye — LLM ko database ka "actual" access nahi hai, usse hum hi text me schema batate hain.
- `run_sql(query)` — koi bhi SQL string execute karta hai aur result ko dict list me convert karke deta hai (taaki JSON me easily convert ho sake API response ke liye). Agar query galat hai (syntax/schema error), SQLAlchemy exception raise karega — yehi exception LangGraph node me catch hoga aur self-healing retry trigger karega.

**Design choice:** Table/columns raw SQL se banaye (SQLAlchemy Core `text()`), ORM models (declarative classes) nahi banaye — kyunki agent khud dynamic SQL likhta hai, humein fixed ORM models ki zaroorat nahi, sirf raw execution chahiye.

**Security note (abhi ke liye basic):** `run_sql` filhal kisi bhi SQL ko run kar sakta hai (SELECT ho ya DELETE/UPDATE). Agle step me isme ek guard lagayenge jo destructive queries (INSERT/UPDATE/DELETE/DROP) ko explicit permission ke bina block karega — ye Phase 3 (HITL) ka simplified version hoga.

---

## Aage jo bhi file banegi, uska explanation yahin niche add hoga.
