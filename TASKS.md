# TASKS

Legend: ✅ done · 🔄 in progress · ⏳ todo · ⛔ blocked (needs user action)

## Phase 0 — Inspect repository ✅
- ✅ Existing: FastAPI skeleton (`/`, `/health`), pydantic settings, `.env` with 3 vars, venv (Python 3.14)
- ✅ Fixed: `requirements.txt` was UTF-16 (PowerShell `pip freeze >`), now UTF-8/LF
- ✅ `git init` (branch `main`); Claude-local files excluded via `.git/info/exclude`

## Phase 1 — Documentation ✅
- ✅ docs/requirements.md, architecture.md, api-contracts.md, data-mapping.md, test-plan.md, setup.md, deployment.md, demo-checklist.md
- ✅ Local-only CLAUDE.md + .claude/ (git-excluded)
- ✅ Initial commits (identity: AmitPrasad212003, confirmed by user)

## Phase 2 — External setup & live contract checks ⏳
Depends on: Phase 1
- ✅ Finding: portal has **no legacy apps**; existing token is a service key (REST only; service keys cannot receive webhooks)
- ✅ HubSpot CLI 8.17.0 installed (Node 24)
- ✅ CLI authenticated (account `open-ai`, portal 247782088)
- ✅ `hubspot-project/` uploaded (build #1, app id 58454528) and installed; 9 scopes granted
- ✅ `HUBSPOT_CLIENT_SECRET` set; `scripts/check_config.py` passes (Forager 200, HubSpot 200, all mapped default properties exist incl. `hs_linkedin_url`)
- ✅ User confirmed `HUBSPOT_ACCESS_TOKEN` is the app's static token
- ✅ Forager free balance was 50 credits (not 150); user is switching to a paid key, so all 5 contacts get email + phone lookups
- ✅ Docs updated for the project-based app and the 50-credit balance
- ✅ Forager OpenAPI bundle checked: reverse-email body `{email}`, phone/personal-email are arrays, work-email `emails[]` shape ambiguous (handled)
- ⏳ One live org search for `openai.com` (1 credit) + one role search (1 credit) → redacted fixtures

## Phase 3 — API clients (TDD) ✅
- ✅ dev deps (pytest, pytest-asyncio, respx), `requirements-dev.txt`, offline network guard
- ✅ config validation (SecretStr) + JSON log redaction
- ✅ HTTP retry/backoff (429/5xx/timeouts, Retry-After, capped)
- ✅ ForagerClient + in-memory credit ledger with budget guard (charges recorded only when Forager charges)
- ✅ HubSpotClient (objects, search, v4 associations, properties; 409-idempotent property creation)
- ✅ 60 offline tests passing

## Phase 4 — Company enrichment ✅
- ✅ `app/mapping.py`: company mapping, location parsing, domain normalisation
- ✅ `CompanyEnrichmentService`: domain/website → org search, name → autocomplete fallback; fill-only name/domain; enriched/partial/not_found/missing statuses
- ✅ `app/hubspot_properties.py` + `scripts/setup_hubspot_properties.py`; run live: 10 company + 7 contact properties created, re-run idempotent
- ✅ 95 offline tests passing

## Phase 5 — Contact enrichment & discovery ✅
- ✅ `TitleFilter`: quoted OR query for Forager `role_title` + local word-bounded include/exclude re-check (exclude wins)
- ✅ Contact mapping: current role (prefers target domain, then most recent), LinkedIn slug parsing, role-search result → person (saves the 1-credit detail lookup)
- ✅ `ContactEnrichmentService`: identify by forager_person_id → LinkedIn → name + company/email domain → reverse email; work email → personal email; phone with per-run limit; credit-budget aware; fill-only names/email; skips already-processed contacts (loop guard)
- ✅ `ContactDiscoveryService`: title-filtered candidates, current employer only, dedupe vs HubSpot (person id, LinkedIn), creates contacts already enriched + associated; 409 duplicate email skipped
- ✅ 153 offline tests passing

## Phase 6 — Webhooks & reliability ✅
- ✅ `app/webhooks.py`: v3 HMAC (5-min window, constant-time, URI decoding) with v1 fallback; legacy + generic `object.creation` parsing
- ✅ `app/jobs.py`: SQLite queue (one active job per object), event dedupe, persistent credit ledger, stale-job requeue
- ✅ Company skip guard (status set → no credits); live Forager balance caps the budget at startup
- ✅ `EnrichmentAutomation` (R4/R5) + `Worker` (retry 429/5xx/network, fail fast on auth/budget/4xx, mark `failed`)
- ✅ FastAPI: `/health`, `/webhooks/hubspot`, admin enrich/discover/reconcile/jobs/credits (`X-Admin-Key`)
- ✅ 227 offline tests passing

## Phase 7 — Acceptance & OpenAI demo ⏳
- ⏳ OpenAI company + 5 contacts enriched live; record limitations

## Phase 8 — Deploy & deliver ⏳
- ⏳ Render deploy (Free + keep-alive, `render.yaml`), webhooks subscribed, acceptance A1–A7, video, submission notes

## Next action
User: put the paid Forager key in `.env` and Render, create the Render service (Blueprint), send the URL. Then: activate webhooks, keep-alive, live OpenAI run while recording.
