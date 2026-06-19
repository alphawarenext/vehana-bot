# Vehana v2 — SaaS Migration Roadmap

## Legend
- ✅ Complete
- 🔄 In Progress / Partial
- ⬜ Not Started

---

## Phase 1 — Foundation: Database, Multi-Tenancy & Auth ✅

| Task | Status |
|---|---|
| Switch from SQLite to PostgreSQL | ✅ |
| Set up Alembic for proper migrations | ✅ |
| `Organization` model with plan, quotas, BYOK fields | ✅ |
| `org_id` FK on every table — no cross-tenant leakage | ✅ |
| `User` model with roles: SUPER_ADMIN, ORG_ADMIN, ORG_MEMBER | ✅ |
| JWT auth — access token (15min) + refresh token (30d) in Redis | ✅ |
| bcrypt password hashing (direct bcrypt, SHA-256 pre-hash — passlib incompatible) | ✅ |
| Fernet AES-256 encryption for API keys in DB | ✅ |
| FastAPI dependency injection (`CurrentUser`, `CurrentOrg`, `OrgAdmin`) | ✅ |
| `seed_db.py` — creates Vehana internal org + super-admin | ✅ |
| `setup_test_agent.py` — creates test VoiceAgent, prints UUID + curl commands | ✅ |
| Auth endpoints: login, logout, refresh, register-org, /me | ✅ |

---

## Phase 2 — Telephony Management ✅

| Task | Status |
|---|---|
| `TelephonyConfig` model — per-org credentials stored encrypted | ✅ |
| Abstract telephony layer: `BaseTelephonyProvider` interface | ✅ |
| `OzonetelProvider` — CPaaS outbound.php with `extra_data` XML (matches v1 behaviour) | ✅ |
| Telephony factory — picks org creds or falls back to Vehana pool | ✅ |
| Redis-backed `CallRegistry` — tracks active calls per org | ✅ |
| Concurrency limit enforcement (`max_concurrent_calls` per org) | ✅ |
| Double-dial prevention (`calls:phone:{org_id}:{phone}` Redis key) | ✅ |
| Per-org DID pool (`did_numbers` JSON array in TelephonyConfig) | ✅ |
| Telephony CRUD API (`GET/POST/PATCH /api/v2/telephony`) | ✅ |
| Inbound/outbound channel split (`max_inbound_calls` / `max_outbound_calls`) | ⬜ |
| Twilio provider implementation | ⬜ |

---

## Phase 3 — LLM Cost Tracking 🔄

| Task | Status |
|---|---|
| `UsageEvent` model — one row per API call | ✅ |
| `DailyCallStats` model — aggregated nightly | ✅ |
| Cost calculator with price table (Gemini, Groq, Sarvam, ElevenLabs) | ✅ |
| `log_llm_usage()`, `log_stt_usage()`, `log_tts_usage()` helpers | ✅ |
| Usage summary / daily / cost-breakdown API endpoints | ✅ |
| BYOK — org supplies own API keys, stored encrypted | ✅ (model ready) |
| **Wire cost logging INTO voice pipeline (Gemini Live calls)** | ⬜ |
| **Wire BYOK API keys into pipeline (use org key → fall back to Vehana pool)** | ⬜ |

---

## Phase 4 — Campaign Engine ✅

| Task | Status |
|---|---|
| Celery + Redis replaces asyncio loop | ✅ |
| `run_campaign` task — fans out `dial_contact` per contact | ✅ |
| `dial_contact` — DND → concurrency → Ozonetel CPaaS dial → CallLog | ✅ |
| Campaign passes WebSocket URL (not answer webhook) in `extra_data` | ✅ |
| Retry logic (max 2 retries, 5min delay) | ✅ |
| Campaign status lifecycle: draft → running → paused → completed | ✅ |
| DND registry with Redis cache | ✅ |
| Call rate limiting (`calls_per_minute_limit`) | ✅ |
| Monthly quota enforcement before launch | ✅ |
| Auto-add to DND when borrower requests during call | ⬜ |

---

## Phase 5 — Architecture Cleanup ✅

| Task | Status |
|---|---|
| 14 route files → 8 clean route files | ✅ |
| All routes under `/api/v2/` prefix | ✅ |
| SQLModel async sessions everywhere | ✅ |
| Shared FastAPI deps (`CurrentUser`, `CurrentOrg`, etc.) | ✅ |

---

## Phase 6 — Analytics & Observability 🔄

| Task | Status |
|---|---|
| `DailyCallStats` aggregation Celery job (nightly 1am IST) | ✅ |
| Monthly org cost rollup (every 30min) | ✅ |
| Monthly quota reset on `billing_reset_date` | ✅ |
| Super-admin dashboard (all orgs, cost, quota) | ✅ |
| Per-org usage & cost dashboard | ✅ |
| Structured JSON logging | ⬜ |
| Average first-response latency tracking | ⬜ |
| Log drain to Datadog / CloudWatch / Loki | ⬜ |

---

## Phase 7 — Voice Pipeline 🔄

| Task | Status |
|---|---|
| `services/pipeline/prompt_builder.py` — builds Gemini system prompt from VoiceAgent config | ✅ |
| `services/pipeline/sarvam.py` — Sarvam STT/TTS WebSocket services (port from v1) | ✅ |
| `services/pipeline/conversation_logger.py` — async logger writes to Postgres | ✅ |
| `services/pipeline/gemini_live.py` — full Gemini Live pipeline (VAD, barge-in, transcript) | ✅ |
| `api/webhooks.py` — `/{agent_id}/answer` (inbound XML) + `/{agent_id}/stream` (WebSocket) | ✅ |
| Webhooks router wired into `main.py`, Silero VAD pre-warmed on startup | ✅ |
| CallRegistry wired into WebSocket connect/disconnect | ✅ |
| Ozonetel `start` event handled in pipeline (gets ucid) | ✅ |
| **Wire `UsageEvent` logging into Gemini Live pipeline** | ⬜ |
| **Wire BYOK — use org's own Gemini/Sarvam key if set** | ⬜ |
| **End-to-end test call on real server** | ⬜ |
| Port smart filler audio (Hindi fillers during STT processing) | ⬜ |
| Port LangGraph state machine agent (for structured EMI flow) | ⬜ |
| Port Hindi number transliteration | ⬜ |
| DND auto-add from intent router during call | ⬜ |

---

## Phase 8 — Deployment ⬜

| Task | Status |
|---|---|
| Run v2 on server port 8001 alongside v1 | ⬜ |
| Nginx config: proxy `/v2/` → port 8001 with WebSocket upgrade headers | ⬜ |
| Update v2 `.env` `BASE_URL` to production URL | ⬜ |
| First real inbound test call (Ozonetel dashboard points to v2 URL) | ⬜ |
| First real outbound campaign test | ⬜ |

---

## Phase 9 — Client Onboarding Portal ⬜

| Task | Status |
|---|---|
| Self-service org registration | ⬜ |
| User invitation system (email link) | ⬜ |
| Frontend v2 (React, multi-tenant routing) | ⬜ |
| Plan enforcement UI (quota used / limit) | ⬜ |
| Per-org API key management UI (BYOK) | ⬜ |

---

## Phase 10 — Production Hardening ⬜

| Task | Status |
|---|---|
| Dockerfile + docker-compose | ⬜ |
| Health check endpoint (Redis + DB ping) | ⬜ |
| Environment configs (dev / staging / prod) | ⬜ |
| Celery worker auto-scaling | ⬜ |
| Stripe billing integration | ⬜ |

---

## Current State

```
PostgreSQL + Alembic:         ✅ Running
Auth + JWT + Redis:           ✅ Working
All models (multi-tenant):    ✅ org_id on every table
API routes (CRUD):            ✅ agents, campaigns, borrowers, telephony, usage, admin
Celery campaign engine:       ✅ DND → concurrency → Ozonetel CPaaS dial
Redis call registry:          ✅ Concurrency + double-dial protection
Cost tracking models:         ✅ Ready (not wired into pipeline yet)
Gemini Live pipeline:         ✅ Ported, WebSocket handler wired
Ozonetel inbound webhook:     ✅ /{agent_id}/answer returns stream XML
Ozonetel outbound:            ✅ CPaaS extra_data approach (matches v1)
Conversation logging:         ✅ Async, writes to Postgres

Cost wired into pipeline:     ⬜
BYOK in pipeline:             ⬜
Deployed on real server:      ⬜ (v2 only tested locally so far)
Frontend v2:                  ⬜
Client onboarding:            ⬜
```

## Immediate Next Steps

1. **Deploy v2 on server** — port 8001, Nginx `/v2/` proxy
2. **First real test call** — inbound via Ozonetel dashboard, outbound via curl
3. **Wire cost logging** — add `log_llm_usage()` call in `gemini_live.py` after each turn
4. **Wire BYOK** — check org's encrypted keys in pipeline before falling back to pool keys
