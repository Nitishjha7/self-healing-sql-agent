# Deployment Guide — Render + Neon

Goal: **ek public URL** jo portfolio me daal sako, jo **hamesha kaam kare**, aur **free** ho.

---

## ✅ Bacha hua kaam — poori checklist

Code sab taiyar hai aur locally test ho chuka hai. Ye cheezein manually karni hain:

### 1. Deploy karna (~30-40 min) — asli baccha kaam

- [ ] **Neon** pe free account → Postgres project → connection string copy (Step 1 neeche)
- [ ] **Render** pe Web Service → GitHub repo connect → Docker runtime (Step 2)
- [ ] Environment variables set karna: `DATABASE_URL`, `GOOGLE_API_KEY`, `GEMINI_MODEL`, `RATE_LIMIT_*`
- [ ] Deploy verify karna — URL kholo, ek question poocho (Step 3)
- [ ] **UptimeRobot** monitor lagana, 10-minute interval (Step 4) — **ye skip mat karna**, iske bina service so jaayegi
- [ ] Live URL README me add karna

### 2. LangSmith pe ek trace khud dekhna (5 min) — chhota par zaroori

Tracing wired hai (`LANGCHAIN_TRACING_V2=true` + key), lekin **abhi tak ek bhi trace dekha nahi gaya.**

- [ ] Local `.env` me `LANGCHAIN_TRACING_V2=true` aur `LANGCHAIN_API_KEY` set karo
- [ ] Ek query chalao jo **actually fail hoke retry kare** — sabse asaan tareeka:
      `docker compose run --rm --no-deps -v "<repo>/eval:/app/eval" backend python -m eval.run_eval --stale-schema --limit 3 --retries 3`
- [ ] [smith.langchain.com](https://smith.langchain.com) pe project kholo, ek run expand karo
- [ ] **Retry chain dekho** — har `generate_sql` call, uska rendered prompt injected error ke saath, raw response, latency, tokens
- [ ] Screenshot le lo (portfolio + interview ke liye)

**Kyun zaroori:** interview me "traces dekhta hoon" bolna aur "kaisa dikhta hai?" pe atak jaana bura lagta hai. **Wiring claim karna aur trace padhna do alag cheezein hain.**

### 3. Guardrails AI validator node (~1 ghanta) — OPTIONAL

Abhi safety prompt-level hai, aur ye har doc me honestly likha hai. Iske bina bhi project defendable hai.

- [ ] `guardrails-ai` ko `langchain-core>=0.3` compatible version pe wapas add karna (purana `0.5.10` conflict karta tha — dekho [CODE_NOTES.md](CODE_NOTES.md))
- [ ] `synthesize_and_validate` ke baad ek alag validator node
- [ ] Docs me `[Planned]` → `[Implemented]` karna, aur INTERVIEW_NOTES ki honesty checklist se wo entry hataana

> **Yahan zyada value nahi hai.** Guardrails is project me bolt-on lagta hai kyunki DB error already deterministic ground truth deta hai. Adaptive CRAG me wo *core feature* hai (grounded answer verify karna) — time hai toh wahan lagao.

### 4. Deploy ke baad docs sync karna

- [ ] README aur ROADMAP me `⬜ Actually deployed` → `✅` karna, live URL ke saath
- [ ] INTERVIEW_NOTES ki [honesty checklist](INTERVIEW_NOTES.md) padh ke confirm karna ki har claim abhi bhi sach hai

---

| Piece | Host | Notes |
|---|---|---|
| App (UI + API, ek service) | **Render** free web service | Docker se deploy, ek hi URL |
| Database | **Neon** free Postgres | Card nahi chahiye, wake ~500ms |
| Keep-alive | **UptimeRobot** free | Service ko sone se rokta hai |

---

## Architecture — ek service, ek URL

Root ka [`Dockerfile`](../Dockerfile) do stages me build karta hai: pehle React app (`npm run build`), phir Python image jisme wo built files `static/` me copy ho jaati hain. FastAPI dono serve karta hai:

```
https://self-healing-sql-agent.onrender.com
  ├─ /              → React chat UI
  ├─ /api/query     → agent (rate-limited)
  ├─ /api/health    → health check
  └─ /health        → same, for uptime pingers
```

**Ek service kyun, do nahi:** split deployment me CORS configure karna padta, do jagah deploy karna padta, aur dono ko warm rakhna padta. Same origin se serve karne pe teeno problem khatam. Local `docker-compose` me abhi bhi nginx frontend serve karta hai — `backend/Dockerfile` usi ke liye hai.

## ⚠️ Render free tier — ek baat pehle jaan lo

Render ka free web service **15 minute inactivity ke baad so jaata hai**, aur jagne me **50+ second** lagte hain. Bina fix ke: recruiter link kholega, blank screen dekhega, tab band kar dega.

**Fix (Step 4):** UptimeRobot har 10 minute `/health` ping karega, toh service kabhi 15 minute idle rahegi hi nahi. Free tier 750 hours/month deta hai — ek service ke liye poora mahina. `/health` deliberately rate limiter se exempt hai, isliye pinger kabhi throttle nahi hoga.

**Render ka free Postgres mat lena** — wo 30 din baad expire ho jaata hai aur portfolio link chupchaap mar jaayega. Neon use karo.

---

## Step 1 — Database (Neon)

1. [neon.tech](https://neon.tech) pe free account → naya project (region Singapore, India ke paas).
2. Connection string copy karo:
   ```
   postgresql://user:pass@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```
3. Table manually nahi banani — `init_db()` startup pe tables create + seed kar deta hai.

> `?sslmode=require` **mat hataana** — Neon plain connection reject karta hai aur app start hi nahi hoga.

## Step 2 — Deploy (Render)

[dashboard.render.com](https://dashboard.render.com) → **New → Web Service** → GitHub repo connect karo.

| Setting | Value |
|---|---|
| Language / Runtime | **Docker** |
| Dockerfile Path | `./Dockerfile` |
| Docker Build Context | `.` (repo root) |
| Instance Type | **Free** |
| Region | Singapore |
| Health Check Path | `/health` |

> Root wala `Dockerfile` chunna hai, `backend/Dockerfile` nahi — wo local compose ke liye hai aur usme frontend build nahi hota.

**Environment variables** (Render dashboard me):

| Key | Value |
|---|---|
| `DATABASE_URL` | Neon wali string, `?sslmode=require` ke saath |
| `GOOGLE_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) se |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` |
| `RATE_LIMIT_REQUESTS` | `5` |
| `RATE_LIMIT_WINDOW` | `60` |

`PORT` set **mat** karna — Render khud inject karta hai, aur Dockerfile use padh leta hai.

Repo me [`render.yaml`](../render.yaml) bhi hai — Render Blueprint se deploy karna ho toh ye settings automatically aa jaayengi (secrets phir bhi dashboard me daalne honge).

Deploy hone pe URL milega: `https://self-healing-sql-agent.onrender.com`. Ye URL **permanent hai** — har redeploy pe wahi rehta hai.

## Step 3 — Verify

```bash
curl https://YOUR-APP.onrender.com/health

curl -X POST https://YOUR-APP.onrender.com/api/query \
  -H "Content-Type: application/json" \
  -d '{"question":"Which department has the highest average salary?"}'
```

Phir browser me URL kholo — chat UI aana chahiye. Ek question poocho aur "Show SQL & steps" khol ke trace dekho.

## Step 4 — Keep-alive (ye skip mat karna)

Iske bina baaki sab bekaar hai — service so jaayegi aur demo 50 second leta rahega.

1. [uptimerobot.com](https://uptimerobot.com) pe free account.
2. **Add New Monitor**:

   | Field | Value |
   |---|---|
   | Monitor Type | HTTP(s) |
   | Friendly Name | SQL Agent |
   | URL | `https://YOUR-APP.onrender.com/health` |
   | Monitoring Interval | **10 minutes** |

Render 15 minute idle pe sulaata hai, toh 10-minute ping hamesha aage rehta hai. Bonus: agar app kabhi down ho toh email aa jaayegi — interview se pehle pata chal jaayega.

---

## Environment variables — poori list

| Variable | Zaroori? | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | ✅ | localhost | Neon string with `?sslmode=require` |
| `GOOGLE_API_KEY` | ✅ | — | Gemini key |
| `GEMINI_MODEL` | — | `gemini-3.5-flash-lite` | Model deprecate ho jaye toh yahan badlo, code me nahi |
| `RATE_LIMIT_REQUESTS` | — | `5` | Per IP |
| `RATE_LIMIT_WINDOW` | — | `60` | Seconds |
| `ALLOWED_ORIGINS` | — | `*` | Single-service me same-origin hai, isliye zaroorat nahi. Split deploy me frontend origin set karna |
| `LANGCHAIN_TRACING_V2` | — | `false` | `true` → traces LangSmith pe |
| `PORT` | — | injected | Render deta hai, khud mat set karna |

---

## Rate limiting — kyun zaroori hai

Public demo pe per-IP rate limit ke bina **API key jal jaayegi.** Gemini free tier poore project ke liye ~15 requests/minute deta hai — sab visitors me shared. Ek bot, ya ek curious recruiter jo 20 questions poochh de, quota khatam kar dega aur uske baad har visitor ko error milega.

[`app/ratelimit.py`](../backend/app/ratelimit.py) per-IP sliding window lagata hai (default 5 questions/minute), aur dono `/health` routes exempt hain.

**Known limitation, honestly:** limiter in-memory hai — restart pe counters reset, aur multi-replica pe har process apna count rakhega. Single-container demo ke liye ye sahi trade-off hai; scale pe Redis chahiye. **Interview me ye khud bolna** — trade-off pata hona hi asli point hai.

---

## Deploy ke baad — checklist

- [ ] UptimeRobot monitor chal raha hai (10-min interval)
- [ ] Rate limit kaam kar raha hai — 6 requests jaldi bhejo, 429 aana chahiye
- [ ] `.env` commit nahi hui — `git ls-files .env` khaali hona chahiye
- [ ] Neon connection string kisi commit me nahi hai
- [ ] README me live URL add kiya
- [ ] Interview se pehle ek baar URL khol ke check kar lena

## Troubleshooting

| Problem | Wajah |
|---|---|
| App start hi nahi hota | `DATABASE_URL` me `?sslmode=require` missing hai |
| Deploy hota hai par 502 | Render ka `$PORT` bind nahi hua — confirm karo ki root wala `Dockerfile` use ho raha hai |
| UI khulti hai, query pe 500 | Zyadatar Gemini quota (429 upstream). Render logs dekho |
| Pehli request 50 sec leti hai | Service so gayi thi — UptimeRobot monitor check karo |
| UI ki jagah JSON dikhta hai | Galat Dockerfile (`backend/Dockerfile`) select ho gaya — usme frontend build nahi hota |
| Build fail: frontend not found | Docker build context `.` (repo root) hona chahiye, `backend` nahi |
