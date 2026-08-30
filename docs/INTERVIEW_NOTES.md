# Self-Healing SQL Agent — Complete Interview Prep

*Author: Nitish | Stack: LangGraph + LangChain + Gemini 2.0 Flash + FastAPI + PostgreSQL + Docker + React*

**Iss doc ka maqsad:** har technical choice ke peeche ka "kyun" likha hua ho, taaki interview me koi bhi cheez pucchi jaye toh defend kar sako — "bas tutorial me aisa tha" wala jawab kabhi na dena pade.

---

## Table of Contents
1. The 30-Second Pitch
2. The Problem (Why This Project Exists)
3. Is This Real or Just a Portfolio Toy?
4. What the System Actually Does (Full Flow)
5. Architecture Overview
6. Core Features & USPs (Deep Dive)
7. **Every Design Decision, Defended** ← the important one
8. Limitations & Mitigations
9. How to Present This in an Interview
10. Anticipated Interview Questions
11. Positioning Alongside My Other Projects
12. Demo Strategy
13. One-Liner for Resume/LinkedIn
14. Quick Reference — AgentState Schema
15. Honesty Checklist (what NOT to claim)

---

## 1. The 30-Second Pitch

> "Most Text-to-SQL demos are one LLM call — if the generated SQL is wrong, the user gets a stack trace. My agent treats a database error as a *signal*, not a failure. When a query fails, the agent feeds the exact Postgres error message plus the SQL that produced it back into the model and regenerates a corrected query, up to three times. It's built as a LangGraph state machine with a conditional edge, so the retry is an actual cycle in the graph — the model sees what broke and fixes that specific fault, instead of just being asked the same question again and hoping for a different sample."

Ek line me: *"SQL agent jo apni galti khud padhta hai aur khud sudhaarta hai — blind retry nahi, error-informed repair."*

**Rule:** pitch pehle bolo, tech baad me. Failure mode se shuru karo, feature list se nahi.

---

## 2. The Problem (Why This Project Exists)

Naive Text-to-SQL ka ek hi assumption hota hai: **LLM pehli baar me sahi SQL likhega.** Ye teen jagah tootta hai:

1. **Schema mismatch** — model column ka naam guess kar leta hai (`salery`, `emp_name`), jo exist hi nahi karta.
2. **Dialect drift** — model SQLite/MySQL syntax likh deta hai jabki database Postgres hai.
3. **Ambiguous phrasing** — "top earners" ka matlab `LIMIT` hai ya `WHERE salary > avg`? Pehla guess galat ho sakta hai.

In teeno cases me database ek **precise, structured error message** deta hai — aur naive pipeline usko throw kar deta hai. Wahi error asal me sabse valuable feedback signal hai. Ye project usko waste nahi hone deta.

---

## 3. Is This Real or Just a Portfolio Toy?

**Agar pucha jaye toh honest raho — isse credibility banti hai.**

Pattern real aur published hai:
- **Self-Refine** (Madaan et al., 2023) — model apne output ko critique karke iterate karta hai.
- **Reflexion** (Shinn et al., 2023) — verbal feedback ko memory me daal ke agla attempt improve karna.
- **Text-to-SQL execution-guided decoding** — literature me established hai ki execution feedback accuracy kaafi badhata hai.
- LangGraph ki apni cookbook me SQL agent with error correction ek reference architecture hai.

Production Text-to-SQL systems (enterprise BI copilots) sab kisi na kisi form me "generate → execute → on error, repair" karte hain.

**Positioning:** *"Main koi naya algorithm claim nahi kar raha. Main dikha raha hoon ki mujhe pata hai naive Text-to-SQL kyun fail hota hai, aur main uska agentic control loop LangGraph se scratch se bana sakta hoon — sirf ek `SQLDatabaseChain` call nahi kar raha."*

Ye line bahut important hai, kyunki LangChain me ready-made `SQLDatabaseChain` hai. Interviewer poochh sakta hai "wo kyun nahi use kiya?" — answer Section 7 me hai.

---

## 4. What the System Actually Does (Full Flow)

1. User natural language me question puchta hai.
2. **`generate_sql`** — plain-text schema description + question ko Gemini (temperature 0) ko bhejta hai, response se SQL extract karta hai (markdown fence strip karke).
3. **`execute_sql`** — pehle destructive-keyword guard (`DROP`/`DELETE`/`UPDATE`/`INSERT`/`ALTER`/`TRUNCATE`), phir Postgres pe query run.
4. **`should_retry`** (conditional edge) — teen me se ek route:
   - **`success`** → synthesize
   - **`retry`** (error hai aur `retry_count < 3`) → wapas `generate_sql`, ab prompt me **pichhla SQL + exact database error** bhi hai
   - **`give_up`** (retries khatam) → synthesize, lekin graceful apology ke saath
5. **`synthesize_and_validate`** — rows ko ek-do line ke natural answer me badalta hai, ek system prompt ke under jo raw table/column names reveal karna mana karta hai.
6. API return karta hai: `final_answer`, `sql_query`, `retry_count`, aur poora `logs` array (node-by-node trace).

---

## 5. Architecture Overview

```
React + Vite Frontend  [Planned]
  |-- Chat UI
  |-- "Show SQL & steps" collapsible (logs array)
  \-- Retry-count badge
                    |
                    v
FastAPI Backend  (POST /query, GET /health)
                    |
                    v
LangGraph StateGraph  (AgentState threaded through every node)

     generate_sql  <------------------+
          |                           | "retry"
          v                           | (error AND retry_count < 3)
     execute_sql --[should_retry]-----+
          |     \
 "success"|      \ "give_up"
          v       v
     synthesize_and_validate --> END
                    |
                    v
              PostgreSQL 16
           (employees table, seeded)
```

**Interview me kyun matter karta hai:** ye dikhata hai ki main orchestration layer (LangGraph), data layer (Postgres/SQLAlchemy), aur API layer (FastAPI) ko alag rakh sakta hoon, aur unko *conditional* control flow se wire kar sakta hoon — linear pipeline se nahi.

---

## 6. Core Features & USPs (Deep Dive)

### 6.1 Error-Informed Regeneration (asli USP)
Retry pe agent **wahi prompt dobara nahi bhejta**. Naya prompt me hota hai: schema + question + jo SQL fail hua + verbatim database exception + "isko fix karo". Ye **reflection** hai, **resampling** nahi.

**Kyun matter karta hai:** temperature 0 pe same prompt dobara bhejne se literally same output aayega. Bina naye information ke retry ka koi matlab hi nahi. Error message hi wo naya information hai.

> **Ye line yaad rakho:** *"Temperature 0 pe blind retry ka koi matlab nahi — same input, same output. Retry tabhi kaam karta hai jab prompt me kuch naya ho. Wo naya cheez database ka error message hai."*

### 6.2 Cyclic Graph, Not a Loop
Retry LangGraph ke `add_conditional_edges` se implement hua hai — `should_retry` runtime pe state padh ke decide karta hai agla node kaun sa hai, aur `generate_sql` pe wapas ja sakta hai.

**Kyun matter karta hai:** ye ek `for` loop se architecturally alag hai — attempt history state object me rehta hai, har node ka execution alag se inspect ho sakta hai, aur aage HITL interrupt / checkpointer plug karna trivial hai (dono LangGraph ke graph-level features hain, jo raw loop me milte hi nahi).

### 6.3 Graceful Degradation
Retries khatam hone pe user ko raw `psycopg2.errors.UndefinedColumn` traceback nahi milta — ek clean sorry message milta hai. Failure bhi ek designed path hai, crash nahi.

### 6.4 Read-Only Enforcement
Destructive keyword guard database call se **pehle** chalta hai, aur `retry_count` ko max set kar deta hai — kyunki "DELETE mat likho" wali request retry karke fix nahi hoti, wo ek policy rejection hai, error nahi.

### 6.5 Full Execution Trace
Har node `logs` list me append karta hai, jo state ke through thread hoti hai aur API response me poori aati hai. Frontend isko timeline banayega: `Generating SQL → Execution failed: column "salery" does not exist → Retry 1 → Generated SQL → Execution succeeded, 3 rows`.

**Kyun matter karta hai:** ye black box nahi hai. Interview me screen pe self-healing *hote hue dikhana* sabse strong moment hai.

---

## 7. Every Design Decision, Defended

Ye section hi is doc ka core hai. Har row: kya kiya, kyun kiya, kya cost hai.

### 7.1 Orchestration

| Decision | Defence | Cost / Trade-off |
|---|---|---|
| **LangGraph, not a LangChain chain** | Mujhe runtime pe branching chahiye — execution ka result decide karta hai agla step. Chain linear hai, usme cycle bana hi nahi sakte. | Thoda zyada boilerplate — nodes aur edges explicitly wire karne padte hain. |
| **LangGraph, not a plain `for` loop** | Loop se retry ho jaata, lekin state machine se attempt history state me structured rehti hai, trace node-by-node inspectable hai, aur HITL interrupt + checkpointer (Phase 3/4) graph-level features hain jo loop me milte hi nahi. | Ek library ki dependency, aur naye developer ke liye seekhne ka curve. |
| **Ready-made `SQLDatabaseChain` nahi use kiya** | Wo ek black box hai — usme main error-repair prompt customize nahi kar sakta, na trace expose kar sakta hoon, na destructive guard inject kar sakta hoon. Poora point hi control loop khud banana tha. | Zyada code likhna pada; agar sirf feature chahiye hota toh built-in faster tha. |
| **3 nodes, 5 nahi** | Har node ka ek clear responsibility hai (generate / execute / synthesize). Isse chhota todne se sirf boilerplate badhta, semantics nahi. | `synthesize_and_validate` do kaam karta hai — validation alag node hoga jab Guardrails AI aayega. |

### 7.2 LLM

| Decision | Defence | Cost / Trade-off |
|---|---|---|
| **Gemini 2.0 Flash** | Usable free tier (portfolio project hai, funded product nahi), short structured outputs pe fast, aur "sirf SQL do, explanation mat do" instruction reliably follow karta hai — jisse parser simple rehta hai. | Vendor-specific rate limits. Mitigation: LangChain chat interface ke peeche hai, `_llm()` me one-line change se provider swap ho jaata hai. |
| **`temperature=0`** | SQL generation deterministic hona chahiye — same question ka same query. Creativity yahan bug hai, feature nahi. Aur reproducible demo/eval ke liye zaroori hai. | Agar model ek particular query pe stuck ho jaye toh sampling se bahar nikalne ka option nahi. Isliye retry me temperature nahi, *naya context* (error) daala jaata hai. |
| **Ek hi LLM instance, dono nodes ke liye** | Generation aur synthesis dono short, structured, low-creativity tasks hain — alag model se koi measurable gain nahi tha, sirf ek aur dependency aur cost. | Agar synthesis kabhi zyada nuanced chahiye ho toh alag bada model use kar sakte hain — abhi over-engineering hoti. |
| **Regex se SQL extract (`_extract_sql`)** | LLM kabhi kabhi ` ```sql ` fence ya ek line explanation add kar deta hai, chahe prompt kuch bhi ho. Ye defensive parsing hai — LLM output ko kabhi trust nahi karna. | Structured output (function calling / JSON mode) zyada robust hota. Ye conscious simplicity choice hai; agar output format flaky nikla toh structured output pe switch karunga. |

### 7.3 Prompting

| Decision | Defence | Cost / Trade-off |
|---|---|---|
| **Schema plain text me prompt me inject** | LLM ka database se koi direct connection nahi hai — usko schema batana hi padega. Plain text isliye kyunki usme *semantic* hints daal sakta hoon (jaise department ke example values: 'Engineering', 'HR'), jo raw DDL me nahi hote. Prompt token cost bhi fixed aur predictable rehta hai. | Schema badla toh description manually update karni padegi. Bade schema pe hand-written description scale nahi karegi — wahan introspection + retrieval (sirf relevant tables) chahiye. |
| **Retry prompt me pichhla SQL + error dono** | Sirf error dena kaafi nahi — model ko dikhna chahiye ki *usne kya likha tha* jo fail hua, warna wo galti dobara kar sakta hai. Dono saath me hi actionable feedback banta hai. | Prompt lamba hota hai, thode zyada tokens. |
| **System prompt me "Only ever write SELECT queries"** | Defence in depth ka pehla layer — model ko destructive query likhne se pehle hi rok do, code guard ko sirf backstop banao. | Prompt-level rule prompt injection se bypass ho sakta hai. Isliye code-level guard bhi hai, aur production me DB-level read-only role hona chahiye. |
| **Synthesis prompt me schema-leakage ban** | Answer me `employees.salary` nahi, "annual salary" aana chahiye. Internal schema expose karna information disclosure hai — attacker ko schema map de deta hai. | Prompt-level enforcement hai, guaranteed nahi. Guardrails AI validator ise deterministic banayega. |

### 7.4 Retry Policy

| Decision | Defence | Cost / Trade-off |
|---|---|---|
| **`MAX_RETRIES = 3`** | Genuine syntax/schema galtiyan pehle ya doosre retry me theek ho jaati hain jab model error dekh leta hai. Jo teen ke baad bhi fail hai wo lagbhag hamesha **semantic** failure hai (question hi answerable nahi) — aur retries badhane se sirf tokens aur latency jalti hai, result wahi rehta hai. Ye ek deliberate cost/latency ceiling hai. | Ek genuinely hard query jo 4th attempt pe ban jaati, wo miss ho jayegi. Isliye ye ek constant hai — eval harness isko sweep karega aur number se justify karega. |
| **Keyword block pe `retry_count = MAX_RETRIES`** | Destructive query ek **policy rejection** hai, syntax error nahi — usko retry karna pointless hai, model wahi query dobara likhega. Turant exit karna hi sahi hai. | Thoda hacky lagta hai (retry counter ko control flow ke liye use karna). Cleaner design ek alag `blocked: bool` state field hota — known refactor. |
| **Failure pe apology, traceback nahi** | Raw exception user ko dena information leak bhi hai aur bekaar UX bhi. | Debugging ke liye error chahiye — isliye wo `logs` me rehta hai, sirf user-facing answer me nahi. |

### 7.5 Data Layer

| Decision | Defence | Cost / Trade-off |
|---|---|---|
| **PostgreSQL, SQLite nahi** | SQLite ka type affinity itna permissive hai ki bahut saari *galat* queries bhi success ho jaati hain — matlab self-healing loop ko wo errors milte hi nahi jinke liye wo bana hai. Postgres ka strict typing aur precise error messages (`column "salery" does not exist`) exactly wahi high-quality feedback signal dete hain jispe retry prompt depend karta hai. Aur production me Postgres hi hoga. | Ek aur container, ek aur moving piece — SQLite file-based hota, zero setup. Demo ke liye Docker Compose ne ye cost absorb kar li. |
| **SQLAlchemy Core (`text()`), ORM models nahi** | Agent khud dynamic SQL likhta hai — mujhe fixed declarative models ki zaroorat hi nahi, sirf raw execution aur connection pooling chahiye. ORM yahan pure overhead hota. | Type safety nahi milti — lekin queries LLM generate kar raha hai, compile-time pe wo waise bhi nahi pata hoti. |
| **`pool_pre_ping=True`** | Container restart ya idle timeout ke baad stale connection pe pehli query fail hoti hai. Pre-ping wo silently handle kar leta hai. Ye chhota sa flag production-awareness dikhata hai. | Har checkout pe ek chhoti round-trip. |
| **Startup pe seed data** | Demo reproducible hona chahiye — clone karo, `docker compose up`, turant query kar sako. Manual migration step demo ko tod deta hai. | Seed idempotent hai (`COUNT(*) == 0` check), lekin ye production migration strategy nahi hai — production me Alembic hoga. |

### 7.6 API & Infra

| Decision | Defence | Cost / Trade-off |
|---|---|---|
| **`logs` API response me expose** | Explainability hi product hai. User ko dikhna chahiye ki agent ne kya socha, kya fail hua, kaise fix kiya — warna wo ek black box hai jo kabhi kabhi galat jawab deta hai. | Internal error messages client tak jaate hain. Internal demo ke liye theek; public product me logs sanitize ya gate karne padenge. |
| **`retry_count` response me** | Ye system ki apni health metric hai — agar retries consistently high hain toh matlab prompt ya schema description improve karni hai. Demo me bhi yahi wo number hai jo self-healing *prove* karta hai. | Koi nahi. |
| **CORS `allow_origins=["*"]`** | Local dev ke liye — frontend alag container/port pe hai. **Ye consciously known issue hai**, deploy se pehle specific origin pe tighten hoga. | Security issue agar aise hi ship ho jaye. Isliye README aur spec dono me explicitly flagged hai. |
| **LangSmith tracing, env-var se on/off** | Do observability layers deliberate hain: `logs` **product** feature hai (API response me jaata hai, UI ki explainability), LangSmith **developer** tool hai (raw prompts, token cost, per-node latency — jo client tak kabhi nahi jaana chahiye). Application me ek line tracing code nahi hai — LangChain ka callback system env vars padh ke khud instrument karta hai. | Ek external service pe dependency. Isliye default `false` hai — bina LangSmith account ke bhi repo chalta hai, zero overhead. |
| **Postgres ka `healthcheck` + `depends_on: service_healthy`** | Backend ko `init_db()` startup pe chalana hai — agar Postgres ready nahi hua toh crash hoga. Ye race ko deterministic banata hai. | Startup thoda slow, kyunki backend wait karta hai. Sahi trade-off. |
| **Dockerfile me requirements pehle, code baad me** | Layer caching — code badalne pe `pip install` dobara nahi chalta. Har rebuild me minute bachte hain. | Koi nahi, ye standard practice hai. |
| **`.env.example` commit, `.env` nahi** | Secrets kabhi repo me nahi. Example file batati hai konse vars chahiye bina values leak kiye. | Koi nahi. |

---

## 8. Limitations & Mitigations

**Ye khud se bolna** — isse maturity dikhti hai. Interviewer ko dhundhne mat do.

### Limitation 1 — Single flat table
Abhi sirf `employees` table hai, toh JOIN complexity ka koi test nahi hua. Real Text-to-SQL ki difficulty multi-table joins me hai, single-table filters me nahi.
**Mitigation:** roadmap ka #1 item — `departments` table with FK. **Ye honestly bolna, chhupana nahi.**

### Limitation 2 — Koi measured accuracy nahi
Abhi tak "kitne % questions sahi answer hue" ka koi number nahi hai.
**Mitigation:** roadmap ka #2 item — 15-20 question ka eval set, aur `MAX_RETRIES=0` vs `MAX_RETRIES=3` compare karke exact accuracy delta nikalna. **Yahi wo number hai jo self-healing loop ka value prove karega** — usse pehle wo ek claim hai, evidence nahi.

### Limitation 3 — Guardrails AI abhi wired nahi hai
`guardrails-ai` requirements me hai, lekin abhi safety sirf prompt-level hai.
**Mitigation:** roadmap pe hai. **Interview me kabhi mat bolna ki Guardrails AI implemented hai** — agar interviewer code kholega toh credibility poori jayegi. Bolo: "safety abhi prompt-level hai, deterministic validator layer next hai."

### Limitation 4 — Keyword guard naive hai
Substring match hai, toh `WHERE comment LIKE '%updated%'` jaisi legitimate query bhi block ho jayegi.
**Mitigation:** conservative fail-safe hai (false positive false negative se behtar hai). Sahi production answer database-level read-only role hai — wo prompt injection se bypass ho hi nahi sakta. Ye ek layered defence ka pehla layer hai, akela solution nahi.

### Limitation 5 — Har request pe graph rebuild
`run_agent()` har call pe `build_graph()` karta hai.
**Mitigation:** compile sasta hai, toh abhi bottleneck nahi — lekin ye ek module-level singleton hona chahiye. Known cleanup. (Iska matlab checkpointer add karte waqt refactor karna hi padega, jo Phase 4 me anyway hoga.)

### Limitation 6 — Koi conversation memory nahi
Har question standalone hai; "aur Marketing me?" jaisa follow-up kaam nahi karega.
**Mitigation:** Phase 4 ka Postgres checkpointer — LangGraph ka built-in persistence isi ke liye hai.

---

## 9. How to Present This in an Interview

**Order:**
1. **Problem pehle (15 sec)** — naive Text-to-SQL ek galat query pe hi toot jaata hai; database ka error waste ho jaata hai.
2. **Solution overview (30 sec)** — Section 1 wali pitch.
3. **2-3 deep dives** interviewer ke hisaab se:
   - *Agentic/systems interviewer* → conditional edges, cyclic graph, state threading
   - *ML/LLM interviewer* → error-informed prompt vs blind resampling, temperature 0 ka logic
   - *Backend interviewer* → FastAPI layering, Docker healthcheck ordering, connection pooling
   - *Product interviewer* → retry budget ka cost/latency trade-off, explainability
4. **Ek trade-off khud se bolo** (Section 7).
5. **Limitations + mitigations** (Section 8) — strong closer.

**Golden rules:**
- Kabhi "maine LangGraph use kiya" se shuru mat karo — jis failure mode ko wo fix karta hai usse shuru karo.
- Har technical choice ko ek outcome se joro (cost, latency, reliability, debuggability).
- Trade-off puche jane se pehle bolo.

**Tech-to-outcome pattern (yaad kar lo):**
> "Maine retry ko LangGraph ke conditional edge se banaya, `for` loop se nahi — sirf fancy dikhne ke liye nahi. Loop se retry ho jaata, lekin attempt history state me structured nahi hoti, trace node-by-node inspect nahi hota, aur HITL approval pause ya cross-session memory add karna — dono LangGraph ke graph-level features hain — baad me poora rewrite maangte. Maine ek din ka extra wiring diya taaki Phase 3 aur 4 ek-ek node ka kaam ban jaye."

---

## 10. Anticipated Interview Questions

### Technical

**Q: LangGraph kyun, plain LangChain chain kyun nahi?**
A: Mujhe runtime pe branching chahiye — execution ka result decide karta hai agla node kaun sa hai, aur mujhe generation node pe *wapas* jaana hai. Chain linear hai, usme cycle possible hi nahi. LangGraph ka `StateGraph` conditional edges deta hai, aur state object poora execution trace har node ke through thread karta hai.

**Q: Ye ek `for` loop hi toh hai, bas fancy naam ke saath?**
A: Behaviour aaj same dikhta hai, architecture nahi. Teen concrete farak: attempt history state object me structured hai (loop me wo local variables hote), har node ka execution alag se inspect/log/test hota hai, aur LangGraph ke graph-level features — `interrupt_before` se HITL approval, checkpointer se cross-session memory — mujhe free me mil jaate hain. Loop me wo teeno cheezein rewrite maangti.

**Q: `SQLDatabaseChain` ready-made hai, wo kyun nahi use kiya?**
A: Kyunki poora project hi wo control loop hai. `SQLDatabaseChain` me main error-repair prompt customize nahi kar sakta, execution trace expose nahi kar sakta, destructive guard inject nahi kar sakta. Agar mujhe sirf feature chahiye hota toh built-in tez tha — mujhe mechanism dikhana tha.

**Q: Retry actually kaam kaise karta hai? Same prompt dobara bhejte ho?**
A: Nahi, aur yahi sabse important detail hai. Temperature 0 pe same prompt ka same output aayega — blind retry ka koi matlab hi nahi. Retry prompt me schema, question, **jo SQL fail hua**, aur **verbatim database error** hota hai. Model ko ek specific fault fix karne ko bola jaata hai. Ye reflection hai, resampling nahi.

**Q: Temperature 0 kyun? Retry ke liye variance nahi chahiye?**
A: Variance galat solution hai. Agar main temperature badha ke retry karta toh main "shayad is baar sahi aa jaye" pe bet kar raha hota. Main uske badle prompt me *naya information* daalta hoon — error message. Determinism SQL ke liye bhi zaroori hai (same question, same query) aur reproducible eval ke liye bhi.

**Q: `MAX_RETRIES = 3` hi kyun?**
A: Genuine syntax/schema errors pehle ya doosre retry me theek ho jaate hain jab model error dekh leta hai. Jo teen ke baad bhi fail hai wo lagbhag hamesha semantic failure hai — question hi answerable nahi — aur retries badhane se sirf latency aur tokens jalte hain. Ye ek cost ceiling hai. Abhi ye reasoned choice hai; eval harness ke baad main isko measure karke number se justify karunga.

**Q: Agar 3 retries ke baad bhi fail ho jaye toh?**
A: `give_up` path synthesize node pe jaata hai jo ek clean apology deta hai — raw traceback user ko kabhi nahi jaata. Error `logs` array me rehta hai debugging ke liye. Failure ek designed path hai, crash nahi.

**Q: LLM ko DROP TABLE likhne se kaise rokte ho?**
A: Teen layers, aur main honest rahunga ki teeno abhi implemented nahi. Layer 1 — system prompt: "only ever write SELECT". Layer 2 — code guard: `execute_sql` database call se pehle destructive keywords reject karta hai. Layer 3, jo abhi nahi hai aur asli answer hai — database-level read-only role. Prompt bypass ho sakta hai, keyword match naive hai, lekin ek Postgres role jise `DELETE` grant hi nahi hai wo prompt injection se bypass nahi ho sakta.

**Q: SQL injection ka risk?**
A: Classic injection yahan alag shakal me hai — user input concatenate nahi ho raha, LLM poori query generate kar raha hai. Toh risk "malicious string escape kar gayi" nahi, "prompt ne model ko destructive query likhwa di" hai. Isliye defence prompt+keyword+DB-role layering hai, parameterization nahi — parameterize karne ko yahan kuch hai hi nahi, query khud hi generated artifact hai.

**Q: SQLite se Postgres kyun switch kiya?**
A: SQLite ka type affinity itna forgiving hai ki bahut saari galat queries bhi chal jaati hain — matlab self-healing loop ko wo errors milte hi nahi jinke liye wo bana hai. Postgres strict hai aur precise error messages deta hai, jo exactly wahi feedback signal hai jispe retry depend karta hai. Aur production me Postgres hi hota.

**Q: Schema LLM ko kaise dete ho? Live introspection?**
A: Abhi plain-text description hard-coded hai. Deliberate — usme main semantic hints daal sakta hoon (department ke actual values), jo raw DDL me nahi hote, aur prompt cost fixed rehta hai. Limitation ye hai ki schema badle toh manually update karni padegi, aur 200-table schema pe ye scale nahi karegi — wahan introspection + sirf relevant tables retrieve karna chahiye.

**Q: Iska scale kaise karoge?**
A: Teen alag bottleneck hain. FastAPI layer stateless hai, horizontally scale ho jaayega. Database pe connection pooling already hai (`pool_pre_ping`), aage PgBouncer. Asli bottleneck LLM latency hai — ek self-healing run me 4 tak generation calls plus synthesis ho sakti hai, toh main successful question→SQL pairs ko cache karunga taaki repeated questions LLM ko hit hi na karein.

**Q: Ise test kaise karoge?**
A: Do levels. Unit — `should_retry` pure function hai, saare routing cases directly test ho jaate hain; `_extract_sql` ko fenced/unfenced/noisy inputs pe test karo. Integration — yahi eval harness hai: fixed question set, expected answers, aur `MAX_RETRIES=0` vs `3` chala ke accuracy delta measure karo. Wo delta hi is project ka asli metric hai.

**Q: Agent galat step le le toh debug kaise karoge?** ← *ye production agentic AI ka sabse common sawaal hai*
A: Do layers hain. `logs` array har node se append hota hai aur API response me jaata hai — wo user-facing explainability hai, aur usse dikh jaata hai ki kaunsa node chala aur kis order me. Lekin wo debugging ke liye kaafi nahi, kyunki usme raw prompt nahi hota. Uske liye LangSmith wired hai — `LANGCHAIN_TRACING_V2=true` plus ek key, aur bas: application me ek line tracing code nahi hai, LangChain ka callback system khud har LLM call instrument kar deta hai. Wahan poori retry chain ek nested trace hai — har `generate_sql` invocation, uska exact rendered prompt injected error ke saath, `_extract_sql` se pehle ka raw response, latency, aur per-attempt token cost.

**Q: Wo tumhe practically kya batata hai?**
A: Teen cheezein jo pehle guesswork thi. Ek — **retry actually kaam kar raha hai ya nahi**: trace me dikh jaata hai ki attempt 2 ne error ko incorporate kiya, ya wahi query dobara likh di. Ye is project ka core mechanism hai, toh usko verify kar paana zaroori hai. Do — **prompt regression**: schema description edit karne se generation kharab hui toh traced prompt me diff dikhta hai. Teen — **cost attribution**: ek retry token me kitna mehnga padta hai, aur slow request me kaunsa node bhaari hai. Ye teeno numbers eval harness ke saath milke retry budget ko reasoned choice se measured choice banayenge.

**Q: Ye tracing sabke liye on hai?**
A: Nahi, opt-in hai — `.env.example` aur `docker-compose.yml` dono me default `false`. Koi repo fork kare toh bina LangSmith account ke chal jaana chahiye, aur tracing off pe zero overhead hai kyunki koi code path uspe depend nahi karta. Aur ye deliberately server-side hai — raw prompts client tak nahi jaane chahiye, isliye wo `logs` array me kabhi nahi daale.

**Q: Deploy kaise karoge?**
A: Postgres Neon pe (serverless free tier), FastAPI Docker image Render pe, React Vercel pe, secrets env vars se inject. Render ka free tier cold-start karta hai toh demo se pehle URL warm kar lunga.

### Product / Business

**Q: Ye actually kahan use hoga?**
A: Koi bhi internal analytics/BI copilot jahan non-technical log data poochhte hain. Wahan self-healing isliye zaroori hai kyunki user SQL error ko debug nahi kar sakta — usko ya toh jawab chahiye ya saaf "nahi mila", stack trace nahi.

**Q: Ye kaam kar raha hai ye kaise measure karoge?**
A: Teen metrics. Execution success rate (kitne % questions ne valid SQL banaya), answer accuracy (expected answers ke against, fixed question set pe), aur average retries per question. Sabse important number: retries ke saath vs bina retries accuracy ka farak — wahi is architecture ka poora business case hai.

**Q: Latency ka kya? Retry toh slow karega.**
A: Karega — worst case 5 LLM calls. Lekin baseline se compare karo: bina retry ke wo query *fail* hoti aur user ko dobara type karna padta, ya wo chhod deta. Ek extra second dekar automatically sahi jawab dena, turant galti dene se behtar hai. Aur happy path pe zero extra cost hai — retry sirf failure pe fire hota hai.

---

## 11. Positioning Alongside My Other Projects

Teeno projects ko ek **pattern** ki tarah present karo, teen alag projects ki tarah nahi:

> **"Agentic Self-Correcting Systems"** — teen projects, ek architectural idea (LLM + self-verification + autonomous correction), teen alag failure domains aur teen alag graph topologies.

| Project | Kya fix karta hai | Graph topology | Correction signal |
|---|---|---|---|
| **Self-Healing SQL Agent** | SQL *execution errors* | **Cycle** — retry edge wapas generation pe | Database ka exception (deterministic, ground truth) |
| **Adaptive CRAG** | Retrieval *relevance* | **Branch** — conditional fallback to web search | LLM grader ka judgement (probabilistic) |
| **Code Guardian** | Code *defects* | **Tool-calling supervisor** — LLM khud decide karta hai kaunse specialists chalane hain | Specialist agents ke findings, synthesize hoke patch |

**Ek aur farak jo alag se bolna** — *kaun* control flow decide karta hai:

- SQL Agent aur CRAG me **LangGraph ke edges** decide karte hain agla node kya hai (`should_retry`, grading branch). Ye deterministic aur auditable hai.
- Code Guardian me **LLM khud** decide karta hai, `bind_tools` se — wo tool call emit karta hai aur graph usko execute karta hai.

> "Dono patterns deliberately hain. SQL agent me control flow deterministic hona *chahiye* — retry ka decision database ke error se aata hai, model ke judgement se nahi, aur usme LLM ko ghusane ka matlab ek reliable signal ko probabilistic bana dena hoga. Code Guardian me model ka judgement hi routing signal hai — kaunsa audit chahiye ye code padh ke hi pata chalta hai. Asli skill ye jaanna hai ki kab kaunsa use karna hai."

**Agar pucha jaye "kya ye overlap karte hain?":**
> "Pattern share karte hain, implementation nahi. Teeno me graph topology alag hai — SQL agent me *cycle* hai, CRAG me *conditional branch*, Code Guardian me *fan-out supervisor*. Correction signal bhi alag hai: SQL agent ko database se deterministic ground truth milta hai, CRAG ko ek LLM grader ka probabilistic judgement — isliye CRAG ko guardrails ki zyada zaroorat hai, SQL agent ka feedback khud reliable hai. Milke ye teeno dikhate hain ki main agentic control flow ke teeno canonical shapes bana sakta hoon."

Ye answer bahut strong hai — ye ek portfolio ko ek *coherent skill story* me badal deta hai.

---

## 12. Demo Strategy

Interviewer ko **self-healing hote hue dikhna** chahiye, sirf ek chat box nahi.

### Scenario 1 — Happy Path
"Who earns more than 80000 in Engineering?"
Flow: `generate_sql` → `execute_sql` (success) → `synthesize`. `retry_count: 0`.
**Talking point:** "Simple case, zero retries — self-healing sirf zaroorat pe fire hota hai, har query pe overhead nahi."

### Scenario 2 — The Correction Path (asli USP)
Aisa question do jo model ko galat column guess karne pe majboor kare — jaise ek aisa concept jo schema me alag naam se hai ("who has been here the longest" jab `join_date` column exist hi nahi karta), ya deliberately schema description me se ek column ka semantic hint hata do.
Flow: `generate_sql` → `execute_sql` **fail** → logs me `column "..." does not exist` → `Retry 1` → corrected SQL → success.
**Talking point:** "Agent ne error khud padha, kya galat tha wo samjha, aur query fix ki — main ne kuch nahi bola. Ye retry nahi, repair hai."

### Scenario 3 — Guard Catch
"Delete all employees from HR."
Flow: guard block, graceful refusal.
**Talking point:** "Ye database tak pahunchta hi nahi. Aur main ise retry nahi karta — ye policy rejection hai, error nahi."

### UI me kya highlight karna hai
- **`retry_count` badge** — 0 vs 1 ka farak hi kahani hai
- **Execution trace / step logs** — sabse impressive part
- **Generated SQL** — dikhao ki black box nahi hai

### Practical tips
- Fixed demo questions rakho jo predictably retry trigger karein — live randomness pe mat jao.
- Trace logs ka screenshot portfolio ke liye rakh lo.
- Render free tier cold start karta hai — demo se 5 min pehle URL warm kar lena.

---

## 13. One-Liner for Resume/LinkedIn

> "Built a Self-Healing Text-to-SQL agent using LangGraph's cyclic state machine — it feeds verbatim PostgreSQL execution errors back into the LLM to autonomously repair failed queries (up to 3 attempts), with read-only enforcement and a full node-by-node execution trace exposed via FastAPI."

---

## 14. Quick Reference — AgentState Schema

```python
class AgentState(TypedDict):
    question: str       # Original natural language question
    sql_query: str      # Most recently generated SQL statement
    query_result: str   # Raw database output (stringified rows)
    error: str          # Exception message; "" means success
    retry_count: int    # Current retry iteration (ceiling: MAX_RETRIES = 3)
    final_answer: str   # Validated natural language response
    logs: List[str]     # Step-by-step trace logs for UI visibility
```

Routing:
```python
def should_retry(state) -> str:
    if state["error"] and state["retry_count"] < MAX_RETRIES: return "retry"
    if state["error"]:                                        return "give_up"
    return "success"
```

---

## 15. Honesty Checklist — Kya NAHI Bolna

Interview me overclaim karna sabse bada risk hai. Agar interviewer code khol le aur claim jhooth nikle, poora project ki credibility jaati hai. **Ye cheezein abhi build nahi hui hain:**

| ❌ Mat bolna | ✅ Bolna |
|---|---|
| "Guardrails AI se output validate karta hai" | "Safety abhi prompt-level hai; deterministic Guardrails validator next step hai" |
| "Complex joins handle karta hai" | "Abhi single table hai — multi-table schema roadmap ka pehla item hai, kyunki JOIN complexity hi asli test hai" |
| "Accuracy X% hai" | "Abhi measure nahi kiya — eval harness bana raha hoon jo retry ke saath vs bina retry accuracy compare karega" |
| "React UI hai" | "Backend complete hai, UI abhi banni hai — demo abhi Swagger se hota hai" |
| "Production ready hai" | "Portfolio project hai; production ke liye read-only DB role, CORS tightening, aur eval chahiye" |
| "LangSmith se traces analyze karta hoon" — **agar tumne ek baar bhi dashboard nahi khola** | Tracing wired hai, lekin **interview se pehle ek baar `LANGCHAIN_TRACING_V2=true` karke ek deliberately failing query chalao aur retry chain ko LangSmith pe khud dekho.** Screenshot le lo. Warna "kaisa dikhta hai?" pucha jaayega aur jawab nahi hoga — wiring claim karna aur trace padhna do alag cheezein hain |

**Kyun ye important hai:** "maine ye nahi banaya, aur mujhe pata hai kyun zaroori hai" wala jawab, "maine sab bana liya" wale jhoothe jawab se *zyada* impressive hota hai. Interviewer gap dhundhte hain — unko khud batana control tumhare paas rakhta hai.
