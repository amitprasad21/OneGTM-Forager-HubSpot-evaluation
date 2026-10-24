# Test Plan

Tooling: `pytest`, `pytest-asyncio`, `respx` (httpx mocking). FastAPI
`TestClient` for HTTP-level tests. Fixtures are JSON files under
`tests/fixtures/`, shaped exactly like the documented response schemas
([api-contracts.md](api-contracts.md)). After Phase 2 they are refreshed from
one redacted real response per endpoint.

- **Default run** (`pytest`): no network, no credentials. A guard fixture fails any test that tries real network I/O.
- **Live run** (`pytest -m live`): opt-in. Requires `RUN_LIVE_TESTS=1` plus real env vars. Spends Forager credits, so each live test states its credit cost.

## 1. Unit tests

| Area | Cases |
|------|-------|
| Config | missing required vars → clear error naming the var, not its value; `repr(settings)` has no secrets |
| Log redaction | tokens, `X-API-KEY`, emails, phones masked |
| HTTP retry | 429 with `Retry-After` honoured; 5xx retried ≤ 3 times; 4xx (non-429) not retried; timeout retried then raised |
| Forager client | correct URL / `X-API-KEY` / account id; 401/403 → `ForagerAuthError`; empty-body contact lookups → `None`; work-email polling to `completed/found`, `completed/not_found`, `failed`, and poll timeout; credit ledger increments only on charged outcomes |
| HubSpot client | bearer header; PATCH body shape; search filters; association call; 429 retry |
| Company mapping | full payload → all properties; missing revenue/headcount → omitted (not 0/""); founded year extraction; address fallback to `location` |
| Contact mapping | current role selection (multiple roles, none current); LinkedIn slug parsing from varied URLs; location from `osm_locations` and from `location.name` fallback; email preference order; extra fields excluded unless flag on |
| Title filter | boolean query building (quoting multi-word terms); include match case-insensitive; exclude wins over include; empty filter = allow all; word-boundary (e.g. "CTO" ≠ "Director") |
| Signature | valid v3 accepted; tampered body rejected; stale timestamp (> 5 min) rejected; v1 valid/invalid; missing headers → 401; URI rebuilt from `PUBLIC_BASE_URL` |
| Webhook parsing | legacy `contact.creation`/`company.creation`; generic `object.creation` with `objectTypeId`; unknown types ignored; malformed JSON → 400 |

## 2. Service / integration tests (mocked APIs)

| ID | Scenario | Expected |
|----|----------|----------|
| I1 | Enrich company by domain | org search called once with `domains`; HubSpot PATCH with mapped props; status `enriched` |
| I2 | Company not found in Forager | status `not_found`, notes set, no other writes |
| I3 | Enrich contact with LinkedIn URL | detail lookup by slug; work email + phone; PATCH; status `enriched` |
| I4 | Contact without LinkedIn, with name + company domain | role search then detail lookup |
| I5 | Email/phone unavailable | status `partial`; notes list missing fields; no fabricated values |
| I6 | Discovery with title filter | only matching titles returned; excluded titles absent; truncated to max |
| I7 | Discovery dedupe | candidate already in HubSpot (by person id / LinkedIn / email) is skipped |
| I8 | Company webhook, contacts exist | company enriched + each contact enriched; no discovery call |
| I9 | Company webhook, no contacts | discovery → contacts created with status `enriched` and associated |
| I10 | Contact webhook | contact enriched |
| I11 | Contact webhook for service-created contact | no Forager calls (loop prevention) |
| I12 | Duplicate eventId delivered twice | processed once |
| I13 | Same object, two different events in flight | one job (dedupe key) |
| I14 | Forager 5xx then success | retried, job succeeds |
| I15 | Forager persistent failure | job retried ≤ 3, then `failed`, status property `failed` |
| I16 | Credit budget exhausted | expensive lookups skipped, status `partial`, note "credit budget" |
| I17 | Malformed Forager response (missing keys) | no crash; treated as not found / partial |
| I18 | Restart with `running` job past lease | re-queued |

## 3. HTTP / deployment tests

- `GET /health` → 200 with `{status, forager_configured, hubspot_configured, db_ok}` and no secrets.
- `POST /webhooks/hubspot` with valid signature → 200 in < 1 s (work deferred).
- Invalid signature → 401. Non-array body → 400.
- `/admin/*` without `X-Admin-Key` → 401.

## 4. Acceptance tests (live, manual + scripted)

| ID | Steps | Pass criteria |
|----|-------|---------------|
| A1 | `GET https://<service>.onrender.com/health` | 200, all `*_configured: true` |
| A2 | Create company "OpenAI" (`openai.com`) in HubSpot UI | within ~1 min: description, revenue, headcount, LinkedIn, HQ location populated; status `enriched` |
| A3 | (A2 continued, no contacts existed) | ≤ 5 title-matching contacts created + associated, each with name, LinkedIn, title, employer fields, city/state/country, and email/phone where Forager has them |
| A4 | Create a contact manually with a LinkedIn URL | enriched within ~1 min |
| A5 | `POST /admin/discover` with `titles=["Engineer"]` vs `["VP","Head"]` | result sets differ and respect filters |
| A6 | Re-send same webhook (HubSpot "test" / replay) | no duplicate contacts, no extra credits |
| A7 | Render logs | no tokens, emails or phone numbers visible |

Credit budget for live acceptance: ≈ 102 credits for the full 5-person target (org search 1 + role search 1 + 5 × (work email 5 + phone 15)); runs on the paid Forager key (see requirements §7).
