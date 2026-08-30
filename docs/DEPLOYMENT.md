# Deployment Guide

Goal: ek **public URL** jo portfolio me daal sako, jo **hamesha kaam kare**, aur **free** ho.

| Piece | Host | Kyun |
|---|---|---|
| Frontend (React static) | **Cloudflare Pages** | Genuinely free, always-on, unlimited bandwidth, card nahi chahiye |
| Backend (FastAPI Docker) | **Google Cloud Run** | 1–2s cold start, 2M requests/month free. Card verification chahiye par is scale pe charge nahi hoga |
| Database (Postgres) | **Neon** | Free serverless Postgres, card nahi chahiye, wake ~500ms |

---

## Pehle: kuch hosts kyun reject kiye

**Render free tier — mat use karna.** 15 minute inactivity ke baad so jaata hai aur cold start **50+ seconds** leta hai. Recruiter link kholega, blank screen dekhega, tab band kar dega. Ye portfolio ke liye deal-breaker hai.

**Cloudflare pe database nahi ho sakta.** Cloudflare **D1** SQLite hai aur sirf Workers se HTTP pe accessible hai — Python container Postgres wire protocol pe usse connect nahi kar sakta. Aur ye project **jaanbujh kar** SQLite chhod ke Postgres pe aaya tha (SQLite itna forgiving hai ki galat queries bhi pass ho jaati hain, jisse self-healing loop ko errors milte hi nahi — dekho [TECHNICAL_SPEC](TECHNICAL_SPEC.md) §2). D1 pe jaana core design decision ulta karna hoga. **Hyperdrive** bhi hai par wo connection pooler hai, database nahi.

**Backend Cloudflare Workers pe nahi chalega** — Python Workers me `psycopg2` / SQLAlchemy nahi hai. Cloudflare Containers paid hai.

**"Hamesha chale" ka sach:** koi bhi free host always-warm nahi deta. Lekin agent khud 2–5 second leta hai (LLM call), toh Cloud Run ka 1–2s cold start usi latency me chhup jaata hai. Ye acceptable hai; Render ka 50s nahi.

**Card bilkul nahi dena?** Backend **Hugging Face Spaces** (Docker SDK) pe daalo — bilkul free, no card, aur sleep sirf 48 ghante inactivity ke baad. Uske saath **UptimeRobot** (free) har 5 minute `/health` ping kare — Space kabhi soyega hi nahi. `/health` rate-limited nahi hai, isliye pinger throttle nahi hoga.

---

## Step 1 — Database (Neon)

1. [neon.tech](https://neon.tech) pe free account, ek project banao (region apne users ke paas — India ke liye Singapore).
2. Connection string copy karo. Wo aisi dikhegi:
   ```
   postgresql://user:pass@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```
3. Bas — koi table manually nahi banani. `init_db()` app startup pe tables create aur seed kar deta hai.

> `sslmode=require` hataana mat — Neon plain connection reject karta hai.

## Step 2 — Backend (Cloud Run)

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

gcloud run deploy sql-agent-backend \
  --source ./backend \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars "DATABASE_URL=postgresql://...neon...?sslmode=require" \
  --set-env-vars "GOOGLE_API_KEY=your_key" \
  --set-env-vars "GEMINI_MODEL=gemini-3.5-flash-lite" \
  --set-env-vars "RATE_LIMIT_REQUESTS=5,RATE_LIMIT_WINDOW=60"
```

Deploy hone pe URL milega — `https://sql-agent-backend-xxxx.a.run.app`. Test:

```bash
curl https://sql-agent-backend-xxxx.a.run.app/health
```

**`ALLOWED_ORIGINS` abhi set mat karo** — Step 3 me frontend ka URL milne ke baad set karenge.

> **Timeout:** Cloud Run ka default request timeout 300s hai, jo kaafi hai. Ek self-healing run worst case 5 LLM calls karta hai (~20-30s).

> **`--min-instances 1`** cold start hata deta hai, **par ye paid hai** (~$5-10/month). Free rakhna hai toh mat lagana.

## Step 3 — Frontend (Cloudflare Pages)

1. [dash.cloudflare.com](https://dash.cloudflare.com) → Workers & Pages → Create → Pages → Connect to Git → apna repo chuno.
2. Build settings:

   | Field | Value |
   |---|---|
   | Framework preset | Vite |
   | Build command | `npm run build` |
   | Build output directory | `dist` |
   | Root directory | `frontend` |

3. Environment variable add karo:

   | Name | Value |
   |---|---|
   | `VITE_API_BASE` | `https://sql-agent-backend-xxxx.a.run.app` |

   > Ye **build-time** variable hai — Vite ise bundle me bake karta hai. Isko badalne ke baad **redeploy karna zaroori hai**, warna purani value chalti rahegi.

4. Deploy → `https://your-project.pages.dev` mil jaayega.

## Step 4 — CORS band karo (ye skip mat karna)

Ab backend ko batao ki sirf tumhara frontend usse baat kar sakta hai:

```bash
gcloud run services update sql-agent-backend \
  --region asia-south1 \
  --set-env-vars "ALLOWED_ORIGINS=https://your-project.pages.dev"
```

Bina iske `ALLOWED_ORIGINS` default `*` rehta hai — koi bhi website tumhare backend ko call kar sakti hai aur tumhari LLM quota jala sakti hai.

## Step 5 — Verify

```bash
curl https://sql-agent-backend-xxxx.a.run.app/health

curl -X POST https://sql-agent-backend-xxxx.a.run.app/query \
  -H "Content-Type: application/json" \
  -d '{"question":"Which department has the highest average salary?"}'
```

Phir browser me Pages URL kholo aur ek question poocho. DevTools → Network me dekho ki request **Cloud Run URL** pe ja rahi hai (localhost pe nahi) aur **CORS error nahi** aa raha.

---

## Environment variables — poori list

| Variable | Kahan | Zaroori? | Notes |
|---|---|---|---|
| `DATABASE_URL` | Backend | ✅ | Neon connection string, `?sslmode=require` ke saath |
| `GOOGLE_API_KEY` | Backend | ✅ | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `GEMINI_MODEL` | Backend | — | Default `gemini-3.5-flash-lite` |
| `ALLOWED_ORIGINS` | Backend | ✅ prod me | Comma-separated. Default `*` — production me kabhi mat chhodo |
| `RATE_LIMIT_REQUESTS` | Backend | — | Default 5 |
| `RATE_LIMIT_WINDOW` | Backend | — | Default 60 (seconds) |
| `VITE_API_BASE` | Frontend | ✅ split deploy me | Backend URL. Build-time — badalne pe redeploy |
| `LANGCHAIN_TRACING_V2` | Backend | — | `true` karo toh traces LangSmith pe jaayenge |

---

## Rate limiting — kyun zaroori hai

Public demo pe **per-IP rate limit ke bina tumhari API key jal jaayegi.** Gemini free tier poore project ke liye ~15 requests/minute deta hai — sab visitors me shared. Ek bot, ya ek curious recruiter jo 20 questions poochh de, quota khatam kar dega aur uske baad har visitor ko error milega.

`app/ratelimit.py` per-IP sliding window lagata hai (default 5 questions/minute). `/health` deliberately exempt hai taaki uptime pingers aur platform health checks kabhi throttle na hon.

**Known limitation, honestly:** limiter in-memory hai — process restart pe counters reset ho jaate hain, aur multiple replicas ke saath har replica apna count rakhega. Single-container demo ke liye ye bilkul sahi trade-off hai; multi-replica pe shared store (Redis) chahiye. Ye interview me khud bolna — trade-off pata hona hi asli point hai.

---

## Deploy ke baad — checklist

- [ ] `ALLOWED_ORIGINS` sirf tumhare Pages URL pe set hai (`*` nahi)
- [ ] Rate limit kaam kar raha hai — 6 requests jaldi bhejo, 429 aana chahiye
- [ ] `.env` commit nahi hui (`git ls-files .env` khaali hona chahiye)
- [ ] Neon connection string kisi commit me nahi hai
- [ ] Interview se pehle ek baar URL khol ke warm kar lena
- [ ] README me live URL add karna

## Troubleshooting

| Problem | Wajah |
|---|---|
| Frontend pe CORS error | `ALLOWED_ORIGINS` me Pages URL nahi hai, ya trailing slash laga hai (nahi lagana) |
| Frontend `localhost` call kar raha hai | `VITE_API_BASE` set nahi hai, ya set karne ke baad redeploy nahi kiya |
| 500 from `/query` | Zyadatar Gemini quota (429 upstream). Cloud Run logs dekho |
| Pehli request slow | Cold start — Cloud Run pe 1-2s normal hai |
| Backend start hi nahi hota | `DATABASE_URL` me `?sslmode=require` missing hai |
