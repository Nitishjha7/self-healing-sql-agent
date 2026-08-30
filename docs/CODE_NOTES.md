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
| ~~`guardrails-ai`~~ | Output validation library | **⚠️ Requirements se hata diya gaya hai.** Do wajah: (1) wo wire hi nahi hua tha — actual validation filhal sirf prompt-level hai (`synthesize_and_validate` ke system prompt me); (2) `0.5.10` `langchain-core<0.3` maangta hai jabki langgraph/langchain/langchain-google-genai teeno `>=0.3` maangte hain — **isse `pip install` fail hota tha aur Docker image build hi nahi hoti thi.** Jab validator node actually banega, tab `langchain-core>=0.3` compatible version pe wapas add hoga. Interview me ise "implemented" mat bolna |
| `sqlalchemy` | Python se SQL database ke saath talk karne ka ORM/toolkit | PostgreSQL ke saath connection aur query execution ke liye — raw psycopg2 se zyada convenient hai |
| `psycopg2-binary` | PostgreSQL driver (actual low-level connector) | SQLAlchemy ko PostgreSQL se baat karne ke liye ye driver chahiye hota hai (SQLAlchemy khud driver nahi hai, wrapper hai) |
| `python-dotenv` | `.env` file se environment variables load karta hai | `DATABASE_URL`, `GOOGLE_API_KEY` jaise secrets ko code me hardcode karne ke bajaye `.env` se read karne ke liye |
| `pydantic` | Data validation / schema library | FastAPI request/response models define karne ke liye (jaise `QueryRequest { question: str }`) — FastAPI internally isi pe based hai |

---

---

## backend/app/db.py

**Kya karta hai:**
- SQLAlchemy `engine` banata hai jo `DATABASE_URL` env var se PostgreSQL se connect hota hai (default fallback localhost pe hai agar env var na mile).
- `init_db()` — `departments` aur `employees` dono tables create karta hai (agar already nahi hain), aur khaali hone pe 4 departments + 10 employees seed karta hai. Ye function container start hone par ek baar call hota hai.
- `_needs_rebuild()` — purana single-table schema detect karta hai (`information_schema` se check karta hai ki `employees.department` TEXT column exist karta hai ya nahi). Mile toh dono tables drop karke naye shape me rebuild. **Kyun:** data sirf seed hai, toh drop safe hai — aur isse existing Docker volume pe bhi `docker compose up` bina kisi manual step ke chal jaata hai. Ye demo-appropriate hai, production migration strategy nahi (wahan Alembic hoti).
- `get_schema_description()` — schema ko plain text me return karta hai. Ye LLM ko prompt me dena hota hai taaki wo columns/table naam sahi se jaan ke SQL banaye — LLM ko database ka "actual" access nahi hai, usse hum hi text me schema batate hain.

**Two-table schema (kyun `department` TEXT ko FK banaya):**
Pehle sirf ek flat `employees` table thi jisme `department` ek TEXT column tha. Problem ye thi ki har question ek single-table `WHERE` filter ban jaata tha — jo model lagbhag hamesha pehli baar me sahi kar leta hai. Matlab **self-healing loop ko heal karne ke liye kuch milta hi nahi tha**, aur project ka core USP demo me kabhi trigger hi nahi hota.

Ab `departments` (id, name, budget, location) alag table hai aur `employees.department_id` uska foreign key hai. Isse model ko join **infer** karna padta hai: "Bangalore me kaun kaam karta hai" ke liye samajhna padega ki location `departments` pe hai, `employees` me department ka naam hai hi nahi, aur `department_id` hi bridge hai. Join galat karna real Text-to-SQL ka sabse common failure hai — aur wo exactly wahi precise Postgres error deta hai (`column e.department does not exist`) jo retry prompt consume karne ke liye bana hai.

**Schema description me teen cheezein deliberately hain** jo raw DDL me nahi hoti:
1. Example values (`'Engineering'`, `'Bangalore'`) — semantic hint
2. Explicit relationship line: `employees.department_id -> departments.id`
3. Ek direct warning: `employees` me department name column hai hi nahi, toh join **mandatory** hai

Live introspection se sirf columns milte, ye guidance nahi — aur is tareeke se prompt token cost bhi fixed aur predictable rehta hai.
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

## LangSmith tracing (env vars only — koi code nahi)

**Kya hai:** `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` + `LANGCHAIN_PROJECT` set karne se LangChain khud har LLM call ko LangSmith pe bhej deta hai — **application me ek line tracing code nahi hai.**

**Kaise kaam karta hai:** LangChain ka callback system in env vars ko import time pe padhta hai aur har `ChatGoogleGenerativeAI` call ko automatically instrument kar deta hai. `.env.example` aur `docker-compose.yml` dono me default `false` hai, toh bina LangSmith account ke bhi repo normally chalta hai — zero overhead, zero behaviour change.

**Kyun liya (aur `logs` array kaafi kyun nahi tha):**
`logs` **user** ke liye hai — readable trace, API response me jaata hai, UI usko dikhati hai. Usme raw prompt nahi hota (aur hona bhi nahi chahiye — wo client tak nahi jaana chahiye).

LangSmith **developer** ke liye hai. Self-healing run inherently multi-step hai — 4 tak generation calls + synthesis, aur **prompt har attempt pe badalta hai**. Jab teen retry ke baad bhi fail ho, asli sawaal ye hota hai: *"attempt 2 pe model ne exactly kya dekha, aur error message ne usko fix kyun nahi karaya?"* — `logs` ye kabhi nahi bata sakta, kyunki wo SQL aur error record karta hai, wo poora prompt nahi jisne unhe banaya.

LangSmith me retry chain ek nested trace ki tarah dikhti hai: har `generate_sql` invocation, uska exact rendered prompt (injected error ke saath), `_extract_sql` se pehle ka raw response, latency, aur per-attempt token cost.

**Teen cheezein jo isse debuggable ho jaati hain:**
- **Prompt regression** — schema description edit karne se generation kharab hui? Traced prompt me diff dikh jaata hai
- **Retry effectiveness** — attempt N+1 ne error actually incorporate kiya, ya wahi query dobara likh di?
- **Cost/latency attribution** — slow request me kaunsa node bhaari hai, aur ek retry token me kitna mehnga padta hai

**Design choice:** do observability layers rakhna deliberate hai, redundant nahi — ek product feature hai (`logs`, client tak jaata hai), doosra developer tool (LangSmith, server-side rehta hai, raw prompts carry karta hai). Isliye LangSmith opt-in hai.

**Interview value:** "agent galat step le toh debug kaise karoge?" agentic AI ka sabse common production sawaal hai. Iska jawab ab "logs array hai" nahi, "LangSmith pe poori retry chain nested trace ki tarah dikhti hai, prompt-level pe" hai.

---

## .env.example

Actual secrets (`.env`) `.gitignore` me hai isliye commit nahi hoga. Ye `.env.example` file sirf **template** hai — batata hai konse env vars chahiye (`DATABASE_URL`, `GOOGLE_API_KEY` etc.) bina real values leak kiye. Isko copy karke `.env` banana hoga aur apni Gemini API key daalni hogi.

## docker-compose.yml fix

Pehle `GROQ_API_KEY` reh gaya tha jab hum Groq use karne wale the — Gemini pe switch karne ke baad ise `GOOGLE_API_KEY` kar diya taaki backend container ko sahi env var mile.

---

## Aage jo bhi file banegi, uska explanation yahin niche add hoga.
