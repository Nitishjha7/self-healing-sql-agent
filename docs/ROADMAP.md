# Roadmap — Interview-Ready Project Plan

**Goal:** Ye project ko ek **interview me dikhane layak, depth-wala project** banana hai (product/startup nahi). Isliye priority sirf un cheezon pe hai jo interview me "impressive" aur "defendable" lagengi.

---

## Current Status (jo ban chuka hai)

- ✅ `backend/app/db.py` — PostgreSQL connection + `employees` table + seed data
- ✅ `backend/app/graph.py` — LangGraph self-healing state machine (Gemini 2.0 Flash ke saath)
- ✅ `backend/app/main.py` — FastAPI (`/health`, `/query` endpoints)
- ✅ `backend/Dockerfile`, `docker-compose.yml`, `.env.example`
- ✅ Basic destructive-query guard (DROP/DELETE/UPDATE/INSERT block)
- ✅ `docs/INTERVIEW_NOTES.md` — pitch, har design decision ka defence, anticipated Q&A, honesty checklist
- ❌ Frontend UI abhi khaali hai (sirf `frontend/Dockerfile` hai)
- ✅ Multi-table schema — `departments` + `employees` FK ke saath, JOIN questions ab possible hain
- ❌ Evaluation/accuracy measurement
- ❌ Guardrails AI validator node (abhi safety sirf prompt-level hai)
- ❌ Deployment

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

**Rate limiting ek real problem nikli:** Gemini free tier kuch models pe sirf **20 requests/day** deta hai, aur ek self-healing run 5 tak LLM calls karta hai. Harness me exponential backoff + poora-question retry daalna pada. Quota per-model hoti hai, isliye eval `-lite` model pe chalta hai (`GEMINI_MODEL` env var), demo standard model pe.

### 3. Frontend chat UI
React + Vite se simple chat interface — question input, answer bubble, aur ek collapsible "Show SQL & steps" section jo `logs` array dikhaye (transparency/explainability dikhane ke liye).

**Kyun zaroori hai:** Interview me live demo dena easy ho jaata hai — Swagger UI professional nahi lagta demo ke liye.

### 4. `docs/INTERVIEW_NOTES.md` — ✅ ban chuka hai
Cheat-sheet ready hai: 30-second pitch, har design decision ka defence (Section 7), limitations + mitigations, anticipated Q&A, demo scenarios, aur ek honesty checklist (kya claim nahi karna).

**Jaise-jaise upar wale items build honge, ise update karna hai** — khaas kar Section 8 (Limitations) aur Section 15 (Honesty Checklist), taaki wo hamesha actual code se match karein.

---

## Deployment Plan

Interview me "live URL hai" bolna bahut acha impression deta hai. Poora stack **free tier** pe deploy ho sakta hai:

| Piece | Kahan deploy hoga | Kyun |
|---|---|---|
| PostgreSQL | [Neon](https://neon.tech) ya [Supabase](https://supabase.com) | Dono ka free tier hai, serverless Postgres, koi credit card nahi chahiye |
| Backend (FastAPI) | [Render](https://render.com) free web service | Docker image se directly deploy ho jaata hai, free tier available |
| Frontend (React) | [Vercel](https://vercel.com) ya [Netlify](https://netlify.com) | Free static hosting, GitHub se auto-deploy |

### Deployment steps (jab code ready ho jaye)

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

## Order of Execution

1. Multi-table schema
2. Evaluation script
3. Frontend chat UI
4. Deployment (Neon + Render + Vercel)
5. Har step ke baad `docs/INTERVIEW_NOTES.md` ko refresh karna — Section 8 (Limitations) aur Section 15 (Honesty Checklist) hamesha actual code se match karein
