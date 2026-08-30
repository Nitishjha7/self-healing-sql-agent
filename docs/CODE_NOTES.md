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
| `guardrails-ai` | Output validation library | Final answer ko check karne ke liye — schema leakage, toxic content, hallucination na ho isliye. **⚠️ Abhi wired nahi hai** — dependency declare hai, lekin actual validation filhal sirf prompt-level hai (`synthesize_and_validate` ke system prompt me). Interview me ise "implemented" mat bolna |
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

---

## backend/app/graph.py

Ye file **project ka core hai** — poora self-healing LangGraph state machine yahin define hai.

**`AgentState`** — TypedDict jo pura context carry karta hai node-to-node: question, current SQL, result, error, retry count, final answer, logs. Spec me diya gaya schema hi hai.

**`_llm()`** — Gemini 2.0 Flash ko LangChain ke through initialize karta hai. `temperature=0` isliye rakha kyunki SQL generation me hume deterministic/precise output chahiye, creative nahi.

**`_extract_sql()`** — LLM kabhi kabhi SQL ko ```sql ... ``` fenced block me ya extra explanation ke saath deta hai. Ye helper sirf clean SQL nikalta hai.

**`generate_sql` node:**
- Agar `state["error"]` khaali hai → fresh prompt banata hai (schema + question).
- Agar error hai (matlab pichhli baar query fail hui) → **self-healing ka core part**: previous SQL + error message dono LLM ko wapas bhejta hai, taaki LLM samajh sake exactly kya galat hua aur fix kare. Ye normal "retry with same prompt" se better hai kyunki LLM ko concrete feedback milta hai.

**`execute_sql` node:**
- Pehle ek **safety check**: agar generated SQL me `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE` jaisa koi keyword hai, query turant block ho jaati hai (retry count ko max pe set karke loop se nikal deta hai). Ye basic guardrail hai jo destructive queries ko rokta hai — Phase 3 (HITL) me isko "approve karo" wale flow me upgrade karenge.
- Warna `run_sql()` (db.py se) call karta hai. Success pe result state me save hota hai; exception aane pe error state me save hoke `retry_count` badhta hai.

**`should_retry` — conditional edge function:**
Ye decide karta hai graph agla kaun sa node jaayega:
- Error hai aur retries `< MAX_RETRIES (3)` → wapas `generate_sql` (retry loop)
- Error hai aur retries khatam → `give_up` (synthesize karega ek apology message ke saath)
- Error nahi hai → `success` (normal synthesis)

Yehi function hai jo LangGraph ko **cyclic graph** banata hai — normal linear chain me ye possible nahi hota.

**`synthesize_and_validate` node:**
- Agar sab retries fail ho gaye, ek clean "sorry" message banata hai (raw exception user ko expose nahi karte).
- Warna LLM se natural-language answer banwata hai. System prompt me explicitly bola hai raw column/table names reveal na kare aur multiple logon ki salary ek saath na dikhaye (basic schema-leakage / privacy guardrail) — ye Guardrails AI library se replace/enhance hoga agle step me, abhi prompt-level safety hai.

**`build_graph()`** — teeno nodes ko wire karta hai:
```
generate_sql → execute_sql → (conditional: retry → generate_sql | give_up/success → synthesize_and_validate) → END
```

**`run_agent(question)`** — external entrypoint jo FastAPI endpoint call karega. Fresh `AgentState` banata hai aur poora graph invoke karta hai, final state return karta hai (jisme `final_answer`, `sql_query`, `logs` sab honge — UI ko yahi dikhana hai).

**Interview-worthy point:** Ye "retry" koi dumb `for` loop nahi hai — ye LangGraph ka **conditional edge** feature use karta hai jisse graph runtime pe decide karta hai kaunsa node next chalega, based on state. Isi wajah se ye ek real state machine hai, sequential script nahi.

---

---

## backend/app/main.py

FastAPI app ka entrypoint — HTTP layer, koi agent logic nahi yahan.

- **`@app.on_event("startup")` → `init_db()`**: container start hote hi table create/seed ho jaati hai, alag se manual step nahi karna padta.
- **`GET /health`**: Docker healthcheck / uptime check ke liye simple ping endpoint.
- **`POST /query`**: Frontend yahi call karega. Body me `{"question": "..."}` bhejna hoga, response me `sql_query`, `final_answer`, `logs` (poora trace), aur `retry_count` milega — UI ko yehi sab dikhana hai transparency ke liye.
- **CORS `allow_origins=["*"]`**: Abhi dev ke liye open rakha hai taaki React (alag port/container) se backend ko call kiya ja sake bina CORS error ke. Production me isko specific frontend domain tak restrict karna chahiye — abhi ke liye note kar liya, baad me tighten karenge.
- **Pydantic models (`QueryRequest`, `QueryResponse`)**: Request/response ka shape enforce karte hain — FastAPI inse automatically validation + `/docs` (Swagger UI) bana deta hai.

---

## backend/Dockerfile

Standard multi-line Python container build:
1. `python:3.11-slim` base (halka image, poora Python nahi, sirf zaroori)
2. `requirements.txt` pehle copy karke install karte hain (Docker layer caching ke liye — agar code badle but requirements na badle, install step dobara nahi chalega)
3. Phir `app/` code copy karte hain
4. `uvicorn` se app run karte hain port 8000 pe

## .env.example

Actual secrets (`.env`) `.gitignore` me hai isliye commit nahi hoga. Ye `.env.example` file sirf **template** hai — batata hai konse env vars chahiye (`DATABASE_URL`, `GOOGLE_API_KEY` etc.) bina real values leak kiye. Isko copy karke `.env` banana hoga aur apni Gemini API key daalni hogi.

## docker-compose.yml fix

Pehle `GROQ_API_KEY` reh gaya tha jab hum Groq use karne wale the — Gemini pe switch karne ke baad ise `GOOGLE_API_KEY` kar diya taaki backend container ko sahi env var mile.

---

## Aage jo bhi file banegi, uska explanation yahin niche add hoga.
