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
- ⛔ User: confirm `HUBSPOT_ACCESS_TOKEN` is now the app's static token (not the service key)
- ⛔ **Forager balance is 50 credits (initial demo credits), not 150** — decide how to cover the 5-person deliverable
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

## Phase 4 — Company enrichment ⏳
- ⏳ company mapping · CompanyEnrichmentService · property setup script

## Phase 5 — Contact enrichment & discovery ⏳
- ⏳ contact mapping · title filter · ContactEnrichmentService · ContactDiscoveryService

## Phase 6 — Webhooks & reliability ⏳
- ⏳ signature verification · payload parsing · SQLite job queue + idempotency · worker · admin endpoints

## Phase 7 — Acceptance & OpenAI demo ⏳
- ⏳ OpenAI company + 5 contacts enriched live; record limitations

## Phase 8 — Deploy & deliver ⏳
- ⏳ Railway deploy, webhooks subscribed, acceptance A1–A7, video, submission notes

## Next action
Phase 4: company mapping + CompanyEnrichmentService + `scripts/setup_hubspot_properties.py` (TDD, offline).
Open user decisions: Forager credit gap; confirm HubSpot token is the app token.
