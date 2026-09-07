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
| `langchain-google-genai` | LangChain ka Gemini-specific connector | Gemini use kar rahe hain (free tier). Model name env-configurable hai (`GEMINI_MODEL`) kyunki Google ke model names deprecate hote rehte hain — `gemini-2.0-flash` aur `gemini-2.5-flash` dono is project ke dauraan 404 dene lage — isi package se Gemini ko LangChain me plug karte hain |
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

**Security note:** `run_sql` technically kisi bhi SQL ko chala sakta hai, isliye guard `execute_sql` node me hai — destructive keywords DB call se **pehle** pakde jaate hain. Writes ab `run_write` se jaate hain, jo alag function hai aur commit karna hai ya rollback ye caller batata hai. **Sahi production answer phir bhi database-level read-only role hai** — wo prompt injection se bypass nahi ho sakta, jabki keyword matching kar sakti hai.

---

---

## backend/app/graph.py

Ye file **project ka core hai** — poora self-healing LangGraph state machine yahin define hai.

**`AgentState`** — TypedDict jo pura context carry karta hai node-to-node: question, current SQL, result, error, retry count, final answer, logs. Spec me diya gaya schema hi hai.

**`_llm()`** — Gemini ko LangChain ke through initialize karta hai (model `GEMINI_MODEL` env var se, default `gemini-3.5-flash-lite`). `temperature=0` isliye rakha kyunki SQL generation me hume deterministic/precise output chahiye, creative nahi.

**`_extract_sql()`** — LLM kabhi kabhi SQL ko ```sql ... ``` fenced block me ya extra explanation ke saath deta hai. Ye helper sirf clean SQL nikalta hai.

**`generate_sql` node:**
- Agar `state["error"]` khaali hai → fresh prompt banata hai (schema + question).
- Agar error hai (matlab pichhli baar query fail hui) → **self-healing ka core part**: previous SQL + error message dono LLM ko wapas bhejta hai, taaki LLM samajh sake exactly kya galat hua aur fix kare. Ye normal "retry with same prompt" se better hai kyunki LLM ko concrete feedback milta hai.

**`execute_sql` node:**
- Pehle ek **safety check** (`is_destructive`): agar generated SQL me `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE` jaisa koi keyword hai — **stateless path pe** query turant block ho jaati hai (retry count max pe set karke loop se nikal jaati hai, kyunki policy rejection retry se theek nahi hoti). **`thread_id` wale path pe ab ye block nahi, approval gate hai** — neeche "HITL approval gate" section dekho.
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

---

## frontend/ — React + Vite chat UI

**Kya hai:** Ek single-page chat interface jo `POST /api/query` call karta hai aur response ko readable bana ke dikhata hai.

| File | Kaam |
|---|---|
| `src/App.jsx` | Poora UI — chat state, fetch call, turn rendering, retry badge, collapsible details |
| `src/App.css` | Layout aur components ki styling |
| `src/index.css` | CSS variables (light + dark), base typography |
| `vite.config.js` | React plugin + dev-server proxy (`npm run dev` ke liye, container me nginx handle karta hai) |
| `nginx.conf` | SPA fallback + `/api/` reverse proxy backend tak |
| `Dockerfile` | Multi-stage — node build, phir nginx serve |

**Design choices aur unke reason:**

- **Koi UI library nahi (Tailwind/MUI nahi)** — UI itni chhoti hai ki plain CSS se kaam ho jaata hai. Ek dependency add karne ka matlab build complexity + bundle size, bina kisi fayde ke. Interview me ye defendable hai: "scope ke hisaab se choose kiya, habit se nahi."
- **Retry badge (`First try` / `Self-healed after N retries`)** — ye UI ka sabse important element hai. `retry_count` hi wo ek number hai jo self-healing ko *prove* karta hai; usko badge banaya taaki demo me turant dikhe.
- **Collapsible "Show SQL & steps"** — default me band, kyunki normal user ko answer chahiye. Khol ne pe executed SQL + poora `logs` array. Ye explainability wala hissa hai — black box nahi.
- **Trace me colour coding** — `Execution failed` / `Blocked` red, `Retry N` amber, `Execution succeeded` green. Warna logs ek undifferentiated wall of text lagti hai aur self-healing ka moment usme kho jaata hai.
- **Nginx proxy, direct backend call nahi** — frontend `/api/query` call karta hai apne hi origin pe, toh browser me CORS ka sawaal hi nahi aata aur backend ko public expose karne ki zaroorat nahi.
- **`proxy_read_timeout 180s`** — nginx ka default 60s hai. Ek self-healing run 5 tak LLM calls kar sakta hai; default timeout usko beech retry me kaat deta, aur user ko 504 milta jabki agent theek kaam kar raha hota.
- **Dockerfile me `package.json` pehle copy** — layer caching, wahi reason jo backend me hai.

**Ports:** `docker-compose.yml` me dono ports override-able hain (`BACKEND_PORT`, `FRONTEND_PORT`) — kyunki 8000 aur 80 machine pe aksar dusre projects le lete hain.

---

## graph.py — read-only narration guard (baad me add hua)

`synthesize_and_validate` ke system prompt me ye lines baad me add hui:

> "This system is STRICTLY READ-ONLY... Never state or imply that data was added, changed, removed or otherwise modified."

**Kyun:** UI testing me "Delete all employees from HR" poocha. Har data-touching layer sahi chala — system prompt ne generation ko SELECT tak rakha, keyword guard ko fire karne ki zaroorat hi nahi padi, database me kuch nahi badla. **Phir synthesizer ne jawab diya: "The employees Anjali Nair and Vikram Singh have been removed from the HR department."**

Kuch remove nahi hua tha. Guard ne data bacha liya, par narration ne jhooth bol diya — aur jis user ko bataya jaye ki deletion ho gayi, uska nuksan waise hi hota hai. **False confirmation apne aap me ek alag harm class hai.**

Ye ek achhi yaad dilane wali cheez hai: mera poora threat model "unauthorised write" pe focused tha, aur wo sab layers kaam kar rahi thi. Gap ye tha ki maine *action* guard kiya, uski *report* nahi.

---

## backend/app/ratelimit.py — per-IP rate limiting

**Kya karta hai:** `/query` pe per-IP sliding window limit (default 5 questions / 60 seconds), env vars se configurable.

**Kyun zaroori hai (ye polish nahi hai):** Public demo pe Gemini free tier **poore project** ke liye ~15 requests/minute deta hai — sab visitors me shared. Ek bot, ya ek curious recruiter jo 20 questions poochh de, quota khatam kar dega aur uske baad **har** visitor ko error milega. Bina rate limit ke demo khud ko tod deta hai.

**Design choices:**
- **In-memory dict of deques, koi Redis nahi** — single-container demo ke liye ye sahi trade-off hai. Multi-replica pe har process apna count rakhega, toh wahan shared store chahiye. **Ye limitation khud bolna interview me** — trade-off pata hona hi asli point hai.
- **`/health` deliberately exempt** — UptimeRobot jaise pingers aur platform ke apne health checks kabhi throttle nahi hone chahiye. Agar `/health` bhi limited hota toh keep-alive ping hi service ko block kar deta.
- **`X-Forwarded-For` ka pehla entry** — Cloud Run/Cloudflare/nginx sab connection khud terminate karte hain, toh `request.client.host` proxy ka IP hota hai. Header spoofable hai, par ye platforms use overwrite karte hain, aur galat hone ka nuksan sirf itna hai ki galat visitor throttle hoga — ye security boundary nahi hai.
- **`MAX_TRACKED_IPS` ceiling** — bina iske dict har naye IP pe badhta rehta. User-controlled keys se bharne wali unbounded dict ek memory leak hi hai.

**Verified:** 5 requests pass, 6th se 429 with `Retry-After`, aur `/health` bilkul throttle nahi hota.

---

## main.py — configurable CORS

`ALLOWED_ORIGINS` env var (comma-separated), default `*`.

**Kyun:** local me frontend nginx ke through same origin pe serve hota hai, toh CORS ki zaroorat hi nahi. Deploy pe frontend (Cloudflare Pages) aur backend (Cloud Run) alag origins pe hote hain — tab CORS chahiye, **par sirf apne frontend ke liye**. `*` chhod dena matlab koi bhi website tumhara backend call kar sakti hai aur tumhari LLM quota jala sakti hai.

`allow_methods` bhi `["*"]` se `["GET", "POST"]` kar diya aur headers sirf `Content-Type` — API sirf yahi use karta hai, baaki khula rakhne ka koi reason nahi.

---

## frontend — VITE_API_BASE

`App.jsx` me `const API_BASE = import.meta.env.VITE_API_BASE || ""`.

Default khaali hai — Docker setup me nginx same origin pe `/api` proxy karta hai, toh relative URL hi chahiye. Split deployment me build ke time `VITE_API_BASE` set hota hai.

**Dhyan rakhna:** ye **build-time** variable hai, runtime nahi — Vite ise bundle me bake kar deta hai. Cloudflare Pages pe value badalne ke baad **redeploy karna zaroori hai**, warna purani value chalti rahegi. Ye ek common gotcha hai.

**429 handling:** frontend `res.status === 429` alag se pakadta hai aur backend ka `detail` message dikhata hai — kyunki throttle hona ek normal, samjhane wali state hai, generic error nahi.

---

## Dockerfile (root) — single-service deployment image

**Kya karta hai:** Do-stage build. Stage 1 me Node React app build karta hai; stage 2 me Python image banti hai aur built files `static/` me copy ho jaati hain. FastAPI dono serve karta hai — API bhi, UI bhi.

**`backend/Dockerfile` se alag kyun:** wo local `docker-compose` ke liye hai jahan nginx alag se frontend serve karta hai. Ye root wala deployment ke liye hai. Dono rehne dene ka reason: local dev me nginx wala setup production-jaisa reverse proxy dikhata hai, aur deploy pe ek service rakhna simplest hai.

**Ek service kyun, do nahi:**
- Render free tier pe ek web service milti hai, aur split deploy me **dono** ko warm rakhna padta
- Same origin matlab **CORS ki zaroorat hi nahi** — ek poori class ki configuration aur uske bugs khatam
- Frontend ka backend URL build-time me bake karne ka jhanjhat nahi (`VITE_API_BASE` khaali rehta hai)

**`CMD` shell form me kyun:** Render (aur zyadatar PaaS) `$PORT` env var inject karte hain jispe bind karna hota hai. Exec form (`["uvicorn", ...]`) me `${PORT}` expand nahi hota — literal string chala jaata. Isliye `sh -c` use kiya, aur `${PORT:-8000}` default rakha taaki local `docker run` bhi chale.

---

## main.py — `/api` prefix aur static mount

**`/api` prefix kyun:** built frontend `/` pe mount hota hai, aur wo mount uske neeche ka har path nigal leta hai. Agar API routes `/query` pe hote toh static mount ke saath collide karte. Sab kuch `/api/*` pe rakhne se dono saath rehte hain.

**Mount sabse last me kyun:** FastAPI routes registration order me match karta hai. `app.mount("/")` pehle likh dete toh wo API routes ko bhi kha jaata. Isliye router include karne ke **baad** mount kiya, aur file me comment bhi likh diya taaki koi galti se upar na le jaye.

**`/health` do jagah kyun:** `/api/health` frontend ke liye consistent hai, aur `/health` root pe isliye kyunki platform health checks aur uptime pingers wahi expect karte hain. Dono rate limiter se exempt.

**`if STATIC_DIR.is_dir()`** — compose setup me `static/` hoti hi nahi (nginx serve karta hai). Bina is check ke app wahan crash kar jaata. Ek hi codebase dono deployment shapes support karta hai.

**nginx me `proxy_pass` se trailing slash hataya** — pehle `http://backend:8000/` tha jo `/api` prefix strip kar deta tha. Ab FastAPI khud `/api` expect karta hai, toh path preserve karna zaroori hai.

---

## render.yaml

Render Blueprint — service settings version control me rakhta hai (dashboard me manually click karne ke bajaye).

**Database yahan define nahi ki** — Render ka free Postgres **30 din baad expire** ho jaata hai. Portfolio link chupchaap mar jaata aur pata bhi na chalta. Neon free tier expire nahi hota.

**Secrets `sync: false`** — matlab value Render dashboard me daalni hai, YAML me nahi. Blueprint commit hota hai; usme API key likhna wahi galti hai jo `.env.example` me key daalna thi.

## backend/app/checkpointer.py — conversation memory (baad me add hua)

**Kya:** ek process-wide `PostgresSaver`, lazy banta hai aur fail-open hai.

**Kyun Postgres, `MemorySaver` kyun nahi:** `MemorySaver` state process me rakhta
hai. Render ka free tier 15 min me sota hai — user wapas aake follow-up poochta
hai aur conversation gayab. Postgres is stack me pehle se hai, to durability ke
liye koi naya service nahi lagta. **Verified:** conversation ke beech backend
container restart kiya, phir usi thread pe "that department's budget?" poocha —
history Postgres se wapas aayi aur reference sahi resolve hua.

**Kyun `pool` aur `autocommit=True`:** `PostgresSaver` ke peeche connection pool
hai, isliye ek hi baar banta hai (har request pe naya pool = connection leak).
`autocommit` ke bina checkpoint writes ek khuli transaction me latak jaate hain
aur agli request unhe dekh hi nahi paati.

**Kyun fail-open:** DB tak pahunch na ho to app crash nahi karti, memory chup-chaap
off ho jaati hai — par API `memory_active: false` lautati hai. Feature down hona
ek cheez hai; **chupke se** down hona doosri, kyunki tab user ko lagta hai agent
bhool gaya jabki memory kabhi on hi nahi thi.

## graph.py — `history`, aur per-turn vs per-conversation state

**Sabse zaroori baat:** checkpointer akela follow-up kaam nahi karata. Wo state ko
durable banata hai; model checkpoint padh nahi sakta. Purane turns ka prompt me
pahunchna bhi utna hi zaroori hai — `_format_history()` wahi karta hai.

Har turn ka **SQL** bhi bhejte hain, sirf angrezi answer nahi: `ORDER BY
AVG(e.salary) DESC LIMIT 1` ye baat answer se zyada saaf batata hai ki "them"
kiski baat hai.

**Aur wo cheez jo checkpointer ne naya paida ki:** ab state turns ke beech survive
karti hai, to har field ka scope tay karna padta hai. `run_agent` ka input dict
checkpointed state ke **upar merge** hota hai — jo key usme nahi hogi wo pichhle
turn se carry ho jaayegi. `history` ko carry hona chahiye; `retry_count`, `logs`,
`error` ko **bilkul nahi** — warna pichhle turn ki 3 retries agle turn ke pehle hi
error pe "give up" karwa dengi, aur trace me pichhle sawaal ki lines dikhengi.
Isliye `run_agent` per-turn fields explicitly reset karta hai. Yahi ek line memory
feature aur memory bug ka farak hai.

`history` pe additive reducer (`Annotated[..., operator.add]`) jaan-boojh ke nahi
lagaya: nodes `{**state, ...}` return karte hain, to har node poori history wapas
bhejta hai — reducer use har baar dobara jod deta aur history exponentially badhti.
Overwrite semantics ke saath sirf `synthesize_and_validate` ek turn add karta hai,
graph ka aakhri node, jo har turn me theek ek baar chalta hai (`generate_sql`
retry loop me dobara chalta hai — wahan append karna ek turn ki teen entries banata).

## backend/tests/ — is project ke pehle tests

10 tests, bina API key aur bina database ke. Ye memory ki **semantics** test karte
hain, model ki quality nahi — kaunsi state carry hoti hai aur kaunsi reset, ye poora
sawaal LLM ke bahar hai. Gemini free tier 20 requests/day deta hai; us quota ko un
tests pe kharch karna jo usse kuch seekh hi nahi rahe, seedha nuksan hai.

`Dockerfile.test` isliye ki is machine pe local Python nahi hai.

---

## HITL approval gate (Phase 3)

**Files:** `graph.py` (`needs_approval`, `await_approval`, `after_approval`, `is_destructive`, `execute_sql`), `db.py` (`run_write`), `main.py` (`/api/approve`), `frontend/src/App.jsx` (approval card).

**Kya karta hai:** destructive query ab hard block nahi hoti — graph rukta hai, exact statement user ko dikhata hai, aur faisle ka intezaar karta hai.

### Teen cheezein jo build karte waqt pata chali

**1. Dedicated approval node banana pada.** Is LangGraph version me dynamic `interrupt()` hai hi nahi — sirf static `interrupt_before=[...]`, jo named node se pehle **har baar** rukta hai. `execute_sql` pe lagate to har `SELECT` bhi ruk jaata. Alag `await_approval` node banane se pause **conditional** ho gaya: routing tay karti hai ki is turn me gate se guzarna hai ya nahi.

**2. HITL checkpointer ke bina possible hi nahi.** Do HTTP requests ke beech graph state kahin save honi chahiye — bina uske resume karne ko kuch hai hi nahi. Isliye stateless path (bina `thread_id`) purane hard block pe hi rehta hai. **Ye gap nahi, sahi behaviour hai:** aisa approval prompt dikhana jise honour hi nahi kiya ja sakta, seedha refuse karne se bura hai. Phase 4 ka Phase 3 se pehle aana ittefaq nahi tha.

**3. Generation prompt badalna zaroori tha, warna poora phase dead code hota.** System prompt me likha tha "only ever write SELECT queries" — ye constraint isliye thi **kyunki gate nahi tha**. Gate banane ke baad bhi wo line chhod dete to destructive SQL kabhi banti hi nahi, gate kabhi fire hi nahi hota, aur phase aisa "kaam karta" dikhta jaise sab theek hai — jabki wahan tak kuch pahunchta hi nahi.

> Ye pehli baar testing me hi pakda gaya: "Delete all employees from HR" poocha aur model ne `SELECT` likh diya, gate skip ho gaya. Ab prompt `hitl_enabled` pe conditional hai.

### `ALLOW_WRITES` — approve hona aur commit hona alag hai

`false` (default) pe approved statement **phir bhi chalta hai** — Postgres plan karta hai, constraints enforce karta hai, affected rows batata hai — aur rollback ho jaata hai. Isse public demo pe approval flow dikhaya ja sakta hai bina kisi visitor ko table khaali karne ki taakat diye.

**Ye approval ka dikhava nahi hai:** response me saaf likha jaata hai ki rollback hua aur kitni rows par asar padta. Safe mode me chalana aur jhoot bolna do alag cheezein hain.

`run_write` ko `run_sql` se alag rakha: `run_sql` contract se read-only hai aur uska caller result set expect karta hai; write ke paas rows hoti hi nahi (`result.keys()` wahan error deta hai). Dono ko mila dena wahi tareeka hai jisse ek "read-only" helper chupke se data badalne lagta hai.

### Synthesis prompt dono taraf guard karta hai

Pehle hardcoded tha "this system is STRICTLY READ-ONLY". `ALLOW_WRITES=true` ke baad wo **ulti** direction me jhoot bulwata: ek write jo sach me commit ho gaya, use "kuch nahi badla" batata. Ab prompt flag pe conditional hai.

Yahi wahi sabak hai jo pehle false-confirmation bug me mila tha ("removed from the HR department" wala jhooth), bas iski mirror image — **na jhoothi confirmation, na jhoothi tasalli.**

Rejection ka jawab LLM se generate hi nahi hota — wo ek fixed policy outcome hai. Model se likhwane ka matlab hota use narrate karte hue kuch aur bolne ka mauka dena.

### 409 kyun, 200 ya 400 nahi

Aisi thread ko approve karna jo pause hai hi nahi (double-click, purana tab) — na caller ki galti hai na server ki kharabi. Chup-chaap 200 lauta dena sabse bura hota: user ko lagta uska faisla laga diya gaya, jabki kuch hua hi nahi.

### Kya verify hua, kya nahi

**Verified (live, Postgres ke saath):** gate destructive query pe rukta hai (`awaiting_approval: true`, khaali `final_answer`), reject karne pe kuch nahi chalta, approve karne pe statement chalta hai aur rollback hota hai (2 rows report, data intact), dobara approve karne pe 409.

**⚠️ Verified nahi:** `ALLOW_WRITES=true` wala commit path asli database pe nahi chalaya — wo sach me rows delete karta aur demo data chala jaata. Us branch ko unit test cover karta hai (fake `run_write` ke saath, dono directions), par end-to-end nahi. **Interview me ye khud bolna.**
