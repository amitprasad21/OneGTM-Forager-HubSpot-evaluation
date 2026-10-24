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
- ⛔ User: `hs account auth` (personal access key) so the CLI can upload a project
- ⏳ Add `hubspot-project/` (static-auth, private app + webhook subscriptions for company/contact `object.creation`), upload, install
- ⏳ User: copy app static token + client secret into `.env`; update api-contracts/setup/deployment docs for the project-based app
- ⏳ `scripts/check_config.py`: Forager `/api/users/current/` (free) → account id + credit balance; HubSpot token check (read-only)
- ⏳ Confirm HubSpot default properties exist (`hs_linkedin_url`, `linkedin_company_page`, `founded_year`, …)
- ⏳ Download Forager OpenAPI bundle; confirm reverse-email request field
- ⏳ One live org search for `openai.com` (1 credit) + one role search (1 credit) → redacted fixtures

## Phase 3 — API clients (TDD) ⏳
- ⏳ dev deps: pytest, pytest-asyncio, respx; `requirements-dev.txt`
- ⏳ config validation + log redaction
- ⏳ http retry/backoff
- ⏳ ForagerClient (+ credit ledger) · HubSpotClient

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
User: confirm the HubSpot private app is standalone and add `HUBSPOT_CLIENT_SECRET` to `.env` (Phase 2).
