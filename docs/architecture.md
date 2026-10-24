# Architecture

## 1. Overview

A single Python service (FastAPI + httpx) deployed on Railway. HubSpot sends
webhooks to it; it acknowledges immediately, queues a job, and a background
worker performs Forager lookups and writes results back to HubSpot.

```
 HubSpot ──(webhook POST, signed)──▶ /webhooks/hubspot ──▶ verify signature
                                                         ──▶ dedupe by eventId
                                                         ──▶ enqueue job (SQLite)  ──▶ 200 OK (< 1 s)
                                                                  │
                                         background worker ◀──────┘
                                                │
             ┌──────────────────────────────────┼──────────────────────────────┐
             ▼                                  ▼                              ▼
   CompanyEnrichmentService          ContactEnrichmentService         ContactDiscoveryService
             │                                  │                              │
             └────────── ForagerClient ─────────┴────────── HubSpotClient ─────┘
```

Operator endpoints (protected by `ADMIN_API_KEY`) and a CLI expose the same
services for manual runs and for the demo (e.g. title-filter demonstration).

## 2. Components

| Module | Responsibility |
|--------|----------------|
| `app/config.py` | Typed settings from env (pydantic-settings). Validates required values at startup; never prints them. |
| `app/logging.py` | Structured JSON logs with redaction of secrets, emails, and phone numbers. |
| `app/clients/http.py` | Shared httpx client factory: timeouts, bounded retries with exponential backoff + jitter on 429/5xx/timeouts, honours `Retry-After`. |
| `app/clients/forager.py` | Thin typed wrapper over the verified Forager endpoints ([api-contracts.md](api-contracts.md)). Tracks credits spent. |
| `app/clients/hubspot.py` | Thin wrapper over HubSpot CRM v3/v4: get/search/create/update companies & contacts, associations, properties. |
| `app/mapping.py` | Pure functions: Forager JSON → HubSpot property dicts ([data-mapping.md](data-mapping.md)). |
| `app/title_filter.py` | Builds Forager boolean `role_title` query and applies a client-side include/exclude safety net. |
| `app/services/*.py` | Business flows for R1–R5. |
| `app/webhooks.py` | Signature verification (v3, v1 fallback), payload parsing (legacy and generic formats), event routing. |
| `app/jobs.py` | SQLite-backed job queue + idempotency store + credit ledger; single async worker started in FastAPI lifespan. |
| `app/main.py` | FastAPI app: `/health`, `/webhooks/hubspot`, `/admin/*`. |
| `scripts/` | CLI: create HubSpot custom properties, run demo enrichment, discover with title filter. |

## 3. Flows

### R1 Company enrichment
1. Read HubSpot company (`domain`, `name`, `forager_enrichment_status`).
2. Resolve in Forager: `organization_search` with `domains=[domain]` (1 credit).
   No domain → organization autocomplete by name → `organization_ids` filter.
3. Map and PATCH company properties; set `forager_organization_id`,
   `forager_enrichment_status=enriched`, `forager_enriched_at`.

### R2 Contact enrichment
1. Read HubSpot contact (+ associated company domain).
2. Identify the person, cheapest first:
   - LinkedIn URL → `person_detail_lookup` by slug (1 credit)
   - name + employer domain → `person_role_search` (1 credit) → detail lookup
   - email only → `person_detail_reverse_lookup/by_email` (5 credits)
3. Contacts (each charged only when found): work email (v2 async job, poll
   until terminal) → personal email fallback (configurable) → phone.
4. Map and PATCH contact; set status properties.

### R3 Discovery with title filter
`person_role_search` with `organization_domains=[domain]`, `role_is_current=true`,
`role_title=<boolean query built from include terms>`; results pass a local
include/exclude filter (Forager full-text matching can be loose), deduped by
Forager person id and against existing HubSpot contacts (LinkedIn URL / email),
then truncated to `max_contacts`.

### R4 Company created webhook
Enrich company (R1) → list associated contacts → if any: enrich each (R2);
if none: discover (R3), create contacts **with enrichment already applied and
status `enriched`**, associate them with the company.

### R5 Contact created webhook
Enrich contact (R2) unless its status is already `enriched`/`in_progress`.

## 4. Reliability & safety

| Concern | Mechanism |
|---------|-----------|
| HubSpot 5 s timeout / retries | Ack after verify + enqueue; work happens in the worker. |
| Duplicate deliveries (retries, batches) | `processed_events(event_id PK)`; job `dedupe_key` (`company:{id}`) unique while pending/running. |
| Webhook loops | We only subscribe to *creation* events; our own property updates do not trigger them. Contacts we create are written with `forager_enrichment_status=enriched`, so the resulting `contact.creation` job is a no-op. |
| Credit exhaustion | Credit ledger in SQLite; `FORAGER_CREDIT_BUDGET` hard cap; phone/personal-email lookups individually toggleable. |
| Transient API errors | Bounded retries (max 3) with backoff on 429/5xx/timeouts; job retried up to 3 times then marked `failed` with error. |
| Partial failure | Each field group is written independently; status `partial` + `forager_enrichment_notes` lists what was missing. |
| Forged webhooks | HMAC verification with HubSpot client secret, 5-minute timestamp window, constant-time compare. |
| PII in logs | Redaction filter; logs carry HubSpot object ids, never emails/phones/tokens. |
| Restart during job | Jobs persisted in SQLite; `running` jobs older than a lease timeout are re-queued at startup. |

### Why SQLite and not Redis/Celery
One instance, low event volume, and a need to survive restarts. SQLite on a
Railway volume gives durable jobs and idempotency with zero extra services.
If the volume is absent the service still runs (DB in ephemeral storage) —
idempotency then degrades to "per deploy", which is documented in deployment.md.

## 5. Non-goals

- Multi-tenant OAuth public app (single portal, private-app token is enough).
- Scheduled re-enrichment / refresh.
- UI beyond FastAPI's OpenAPI docs.
