# Roadmap — Interview-Ready Project Plan

**Goal:** Ye project ko ek **interview me dikhane layak, depth-wala project** banana hai (product/startup nahi). Isliye priority sirf un cheezon pe hai jo interview me "impressive" aur "defendable" lagengi.

---

## Current Status (jo ban chuka hai)

- ✅ `backend/app/db.py` — PostgreSQL connection + `employees` table + seed data
- ✅ `backend/app/graph.py` — LangGraph self-healing state machine (Gemini 2.0 Flash ke saath)
- ✅ `backend/app/main.py` — FastAPI (`/health`, `/query` endpoints)
- ✅ `backend/Dockerfile`, `docker-compose.yml`, `.env.example`
- ✅ Basic destructive-query guard (DROP/DELETE/UPDATE/INSERT block)
- ❌ Frontend UI abhi khaali hai
- ❌ Multi-table schema (abhi sirf ek table hai)
- ❌ Evaluation/accuracy measurement
- ❌ Deployment

---

## Priority Order (interview-focused)

### 1. Multi-table schema (JOIN complexity)
Abhi sirf `employees` table hai — bahut flat/simple hai. Ek `departments` table add karenge (id, name, budget, location) aur `employees.department` ko foreign key bana denge.

**Kyun zaroori hai:** Interview me sabse common sawaal hota hai "complex joins kaise handle kiye" — single table ke saath ye sawaal answer hi nahi ho sakta.

### 2. Evaluation script (sabse strong proof-of-work)
Ek `eval/questions.json` file banayenge — 15-20 natural language questions with expected SQL/answer. Ek script (`eval/run_eval.py`) sabko agent ko bhejega aur measure karega:
- Kitne % sahi answer aaye
- Average retries per question
- Retry ke bina (`MAX_RETRIES=0`) vs retry ke saath accuracy ka farak

**Kyun zaroori hai:** "Maine sirf bana ke chhod diya" vs "maine apna system measure kiya" — ye farak interviewer turant pakadta hai. Numbers dikhana (e.g. "self-healing loop se accuracy 68% se 91% ho gayi") bahut strong hota hai.

### 3. Frontend chat UI
React + Vite se simple chat interface — question input, answer bubble, aur ek collapsible "Show SQL & steps" section jo `logs` array dikhaye (transparency/explainability dikhane ke liye).

**Kyun zaroori hai:** Interview me live demo dena easy ho jaata hai — Swagger UI professional nahi lagta demo ke liye.

### 4. `docs/INTERVIEW_NOTES.md`
Sab kuch consolidate karke ek cheat-sheet:
- 30-second elevator pitch
- Likely interview questions + tumhare answers ("kyun LangGraph", "retry limit 3 kyun", "Guardrails kya validate karta hai", "SQLite se Postgres kyun switch kiya")
- Architecture diagram apne shabdon me explain

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
5. `docs/INTERVIEW_NOTES.md` (sabse last, jab sab kuch build ho chuka ho)
