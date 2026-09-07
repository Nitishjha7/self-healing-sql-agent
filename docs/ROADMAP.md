# Roadmap — Interview-Ready Project Plan

**Goal:** Ye project ko ek **interview me dikhane layak, depth-wala project** banana hai (product/startup nahi). Isliye priority sirf un cheezon pe hai jo interview me "impressive" aur "defendable" lagengi.

---

## Current Status (jo ban chuka hai)

- ✅ `backend/app/db.py` — PostgreSQL connection + `departments` & `employees` tables (FK) + seed data
- ✅ `backend/app/graph.py` — LangGraph self-healing state machine (Gemini, model env-configurable)
- ✅ `backend/app/main.py` — FastAPI (`/health`, `/api/query`, `/api/approve`)
- ✅ `backend/Dockerfile`, `docker-compose.yml`, `.env.example`
- ✅ **HITL approval gate (Phase 3)** — destructive statement ab block nahi hota, rukta hai:
  `interrupt_before` ek dedicated `await_approval` node pe, `/api/approve` se resume,
  aur `ALLOW_WRITES` tay karta hai ki approved statement commit ho ya chal ke rollback ho.
  **Verified live:** gate ruka (`awaiting_approval: true`), reject pe kuch nahi chala,
  approve pe statement chala aur rollback hua (2 rows report, data intact), dobara
  approve karne pe 409.
  ⚠️ `ALLOW_WRITES=true` wala commit path asli DB pe nahi chalaya (wo sach me rows
  delete karta) — sirf unit test se covered hai.
  **Do cheezein build karte waqt pata chali:** (1) HITL checkpointer ke bina possible
  hi nahi — isliye Phase 4 ka pehle aana zaroori tha; (2) generation prompt ki
  "only SELECT" line hataani padi, warna destructive SQL banti hi nahi aur poora
  phase dead code ban jaata.
- ✅ `docs/INTERVIEW_NOTES.md` — pitch, har design decision ka defence, anticipated Q&A, honesty checklist
- ✅ Frontend chat UI — React + Vite, retry badge + collapsible SQL/trace, Nginx proxy ke saath
- ✅ Multi-table schema — `departments` + `employees` FK ke saath, JOIN questions ab possible hain
- ✅ Evaluation harness + measured results — 3 conditions, [eval/RESULTS.md](../eval/RESULTS.md)
- ✅ LangSmith tracing wired (opt-in env vars)
- ✅ **Conversation memory** — `app/checkpointer.py` (`PostgresSaver`, lazy + fail-open),
  `AgentState.history`, `_format_history()` prompt block, API pe `thread_id` +
  `memory_active`, UI me "New conversation" + memory badge + follow-up chips.
  **Verified live:** turn 1 "Which department has the highest average salary?" → Engineering;
  turn 2 "How many people work **there**?" → `WHERE d.name = 'Engineering'` → 4.
  Bina `thread_id` ke wahi sawaal → `SELECT COUNT(*) FROM employees` → **10, confidently galat**.
  Backend container restart karke turn 3 bhi chala — history Postgres se wapas aayi
  (yahi `MemorySaver` pe `PostgresSaver` choose karne ka asli reason hai).
- ✅ **Pehle 10 tests** — `backend/tests/test_memory.py`, bina API key aur bina DB ke.
  Sabse zaroori invariant: har naye sawaal pe per-turn fields (`retry_count`, `logs`,
  `error`…) reset hote hain aur sirf `history` carry hoti hai. Ye sawaal checkpointer
  se **pehle tha hi nahi** — tab har invocation khaali state se shuru hoti thi.
- ❌ Guardrails AI validator node (optional — abhi safety prompt-level hai, docs me honestly marked)
- ✅ Deployment guide + rate limiting + configurable CORS — [docs/DEPLOYMENT.md](DEPLOYMENT.md)
- ❌ Actually deployed (live URL abhi nahi hai) — bacha hua kaam [DEPLOYMENT.md](DEPLOYMENT.md) ke top pe checklist me hai

---

## Priority Order (interview-focused)

### 1. Multi-table schema (JOIN complexity) — ✅ DONE
`departments` table (`id`, `name`, `budget`, `location`) add ho gaya, aur `employees.department` TEXT column ki jagah ab `department_id INTEGER REFERENCES departments(id)` hai.

**Kyun zaroori tha:** Interview me sabse common sawaal hota hai "complex joins kaise handle kiye" — single table ke saath ye sawaal answer hi nahi ho sakta tha. Aur technically bhi: flat table pe har question ek `WHERE` filter ban jaata tha, jo model lagbhag hamesha sahi kar leta hai — matlab **self-healing loop ko heal karne ke liye kuch milta hi nahi tha.** Ab model ko join *infer* karna padta hai, aur join galat karna hi real Text-to-SQL ka sabse common failure hai.

**Kya kiya:**
- `get_schema_description()` me dono tables, explicit `employees.department_id -> departments.id` relationship line, aur ek direct statement ki `employees` me department name column hai hi nahi (toh join mandatory hai)
- `generate_sql` prompt me "join across tables where the question needs data from more than one"
- `init_db()` me purane single-table schema ka detection (`information_schema` se) + rebuild — taaki existing Docker volume pe bhi `docker compose up` bina manual step ke chale
- Seeding idempotent hai (dono tables sirf tab seed hote hain jab count 0 ho)

**Verified:** FK constraint DB me present hai, JOIN + GROUP BY query chalti hai, purana schema mile toh rebuild hota hai, aur dobara `init_db()` chalane pe duplicate nahi aate.

**Ab ye demo questions possible hain (pehle nahi the):**
- "Which department has the highest average salary?" — JOIN + GROUP BY + ORDER BY
- "Who works in Bangalore?" — location `departments` pe hai, employee `employees` pe
- "Which department spends the most of its budget on salaries?" — JOIN + SUM + ratio

### 2. Evaluation script (sabse strong proof-of-work) — ✅ BUILT
`eval/questions.json` (20 questions + gold SQL + difficulty tags) aur `eval/run_eval.py` ban gaye. Details [eval/README.md](../eval/README.md) me hain.

**Metric — execution accuracy:** gold SQL aur agent ka SQL dono chalate hain, **result sets** compare karte hain. SQL string match nahi (ek question ke bahut saare equally-correct SQL hote hain), aur LLM-as-judge nahi (wo reliability problem ko ek unmeasured component me daal deta — poora point hi measurement tha).

**Do numbers report hote hain:**
- **Accuracy** (headline) — gold ka answer agent ke result me contain ho, same row count ke saath
- **Strict** — exact set-of-rows equality

Relaxed headline isliye kyunki questions projection specify hi nahi karte — "Who is the highest paid employee?" ka `SELECT name` bhi sahi hai aur `SELECT name, salary, role` bhi. **Ye pehle smoke test me hi pakda gaya**: strict-only metric ne ek bilkul sahi answer FAIL kar diya tha kyunki agent ne extra columns diye the.

**Kyun zaroori hai:** "Maine sirf bana ke chhod diya" vs "maine apna system measure kiya" — ye farak interviewer turant pakadta hai.

**Rate limiting ek real problem nikli:** Gemini free tier kuch models pe sirf **20 requests/day** deta hai, aur ek self-healing run 5 tak LLM calls karta hai. Harness me exponential backoff + poora-question retry daalna pada. Quota per-model hoti hai, isliye `GEMINI_MODEL` env var se model switch kar sakte hain.

**Results — teen conditions chalayi, sirf schema description badla:**

| Condition | Retries off | Retries on | Delta | Avg retries |
|---|---|---|---|---|
| Production schema (hand-tuned) | 95% | 95% | **+0pp** | 0.00 |
| Degraded schema (bare column list) | 90% | 90% | **+0pp** | 0.00 |
| **Stale schema (galat column names)** | **15%** | **30%** | **+15pp** | 2.25 |

**Sabse important seekh:** pehli do conditions me loop ek baar bhi fire nahi hua (`avg retries = 0.00`) — achhe prompt ke saath model galat query likhta hi nahi. Toh wo runs **prompt** measure kar rahe the, **architecture** nahi.

Isliye teesri condition banayi — schema description me aise column names jo exist hi nahi karte (schema drift, real deployments ka sabse common breakage). Wahan queries actually fail hoti hain, Postgres `HINT: Perhaps you meant to reference the column "employees.name"` deta hai, wo hint retry prompt me jaata hai, aur **accuracy double ho jaati hai.**

Poora analysis + har failure ka breakdown [eval/RESULTS.md](../eval/RESULTS.md) me hai.

⚠️ **Interview me number hamesha condition ke saath bolna** — bina context ke "accuracy double ho gayi" bolna cherry-picking hai.

### 3. Frontend chat UI — ✅ DONE
React 18 + Vite chat interface. Question input, answer bubbles, aur ek collapsible "Show SQL & steps" section jo executed SQL aur poora `logs` array dikhata hai — trace me failures red, retries amber, success green (transparency hi USP hai, toh wahi visually highlight kiya).

Ek **retry badge** har answer pe: "First try" (green) ya "Self-healed after N retries" (amber). Yehi wo ek cheez hai jo demo me self-healing ko *dikhata* hai.

Nginx multi-stage build se serve hota hai, `/api/` reverse proxy backend tak. Proxy timeout 180s rakha — default 60s ek self-healing run (5 tak LLM calls) ko beech me kaat deta hai.

**Kyun zaroori hai:** Interview me live demo dena easy ho jaata hai — Swagger UI professional nahi lagta demo ke liye.

**🐛 Ek serious bug isi UI testing me mila:** "Delete all employees from HR" poocha — guard ne sahi kaam kiya, SELECT hi chali, data safe raha. **Lekin synthesizer ne jawab diya "The employees Anjali Nair and Vikram Singh have been removed from the HR department."** Kuch remove nahi hua tha. Guard ne data bachaya, narration ne jhooth bola.

Fix synthesis prompt me hai (system ab explicitly janta hai ki wo read-only hai aur kabhi modification claim nahi karega). **Lesson:** action ko guard karna aur us action ki *report* ko guard karna do alag cheezein hain — aur ye gap sirf end-to-end UI testing se mila, kyunki har component alag-alag sahi kaam kar raha tha.

### 4. `docs/INTERVIEW_NOTES.md` — ✅ ban chuka hai
Cheat-sheet ready hai: 30-second pitch, har design decision ka defence (Section 7), limitations + mitigations, anticipated Q&A, demo scenarios, aur ek honesty checklist (kya claim nahi karna).

**Jaise-jaise upar wale items build honge, ise update karna hai** — khaas kar Section 8 (Limitations) aur Section 15 (Honesty Checklist), taaki wo hamesha actual code se match karein.

---

## Deployment Plan

Interview me "live URL hai" bolna bahut acha impression deta hai. Poora stack **free tier** pe deploy ho sakta hai:

| Piece | Kahan deploy hoga | Kyun |
|---|---|---|
| PostgreSQL | **[Neon](https://neon.tech)** | Free, no card. **Render ka free Postgres mat lena — 30 din baad expire ho jaata hai** aur link chupchaap mar jaayega |
| App (UI + API, ek service) | **[Render](https://render.com)** free web service | Docker se deploy, ek hi URL. Free tier 15 min me sota hai — **UptimeRobot** har 10 min `/health` ping karke jagaye rakhta hai |
| ~~Frontend alag~~ | — | Zaroorat nahi: FastAPI hi built React serve karta hai, toh ek hi URL aur CORS ka jhanjhat nahi |

### Deployment steps

**Detailed guide ab [DEPLOYMENT.md](DEPLOYMENT.md) me hai** — ye section historical hai. Do cheezein badli:

1. **Render chhod diya** — free tier 15 min me sota hai aur cold start 50+ sec leta hai, jo portfolio demo ke liye deal-breaker hai. **Cloud Run** (1-2s cold start) ya **HF Spaces + UptimeRobot** better hai.
2. **Frontend Vercel ki jagah Cloudflare Pages** — dono free hain, Cloudflare pe unlimited bandwidth hai.

Purane steps neeche reference ke liye:

1. **Database (Neon)**
   - Neon pe free account banao, ek Postgres project create karo
   - Connection string milega — wahi `DATABASE_URL` env var me daalna hai

2. **Backend (Render)**
   - GitHub repo ko Render se connect karo
   - "New Web Service" → repo select karo → `backend/Dockerfile` detect ho jayega
   - Environment variables set karo: `DATABASE_URL` (Neon wala), `GOOGLE_API_KEY`
   - Deploy hote hi ek public URL milega (e.g. `https://self-healing-sql-agent.onrender.com`)

3. **Frontend (Vercel)**
   - GitHub repo connect karo, root directory `frontend` set karo
   - Build command: `npm run build`, output: `dist`
   - Environment variable: backend ka Render URL (taaki frontend usko `/query` call kar sake)
   - Deploy → public URL milega

4. **Local `.env` ko kabhi commit mat karna** — `.gitignore` already `.env` ko exclude karta hai, sirf `.env.example` commit hota hai.

**Note:** Render ka free tier thoda "sleep" hota hai (inactivity ke baad cold start lagta hai) — interview se pehle ek baar URL khol ke warm kar lena.

---

## Future — beyond the interview-ready scope

In wo priorities me shaamil nahi hai (jo sab upar "interview-focused" hain), lekin agli badi feature direction ye hai — dono planned only hain, abhi implement nahi hui:

### Phase 5 (planned): AI-generated dashboards
Abhi agent sirf ek sawaal → ek answer deta hai (chat mode). Dashboard mode isi ke upar layer hoga, replace nahi karega:
- User bole "Create a dashboard for department performance" → agent multiple related questions me todta hai, har ek ke liye existing self-healing `generate_sql` → `execute_sql` loop chalata hai
- Result sets analyze karke har ek ke liye chart type suggest karta hai (KPI card / bar / donut / table)
- Frontend me naya "Dashboard" tab hoga, existing "Chat" tab ke saath — dono coexist karenge
- Har widget ka "View SQL" available rahega (transparency wahi principle jo chat mode me hai)
- Chat se follow-up karke dashboard modify karna bhi possible hoga ("Add employee count to this")

### Phase 6 (planned): Power BI export
Generated dashboard ka data + queries Power BI me export, taaki user AI-generated analytics ko apne existing Power BI workflow me continue kar sake.

**Kyun abhi nahi:** Ye dono naye subsystem hain (multi-query orchestration, chart-type inference, naya UI surface) — interview-ready core (self-healing + memory + eval) complete hone ke baad hi shuru karna sahi hai, taaki scope creep se core weak na ho.

---

## Order of Execution

1. Multi-table schema
2. Evaluation script
3. Frontend chat UI
4. Deployment (Neon + Render, single service) — guide ready, [DEPLOYMENT.md](DEPLOYMENT.md)
5. Har step ke baad `docs/INTERVIEW_NOTES.md` ko refresh karna — Section 8 (Limitations) aur Section 15 (Honesty Checklist) hamesha actual code se match karein
