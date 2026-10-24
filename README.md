# Forager × HubSpot Enrichment

A Python service that enriches HubSpot companies and contacts with
[Forager](https://forager.ai) data. HubSpot webhooks trigger it automatically.
It was built for the OneGTM Lab AI Automation Engineer evaluation.

| Requirement | Where |
|-------------|-------|
| 1. Enrich companies (description, revenue, headcount, …) | [`app/services/company_enrichment.py`](app/services/company_enrichment.py) |
| 2. Enrich contacts (name, LinkedIn, title, employer, email, phone, location) | [`app/services/contact_enrichment.py`](app/services/contact_enrichment.py) |
| 3. Find contacts at a company, filtered by job title | [`app/services/contact_discovery.py`](app/services/contact_discovery.py), [`app/title_filter.py`](app/title_filter.py) |
| 4. Company-created webhook: enrich the company, then its contacts, or find contacts if it has none | [`app/services/automation.py`](app/services/automation.py) |
| 5. Contact-created webhook: enrich the contact | [`app/services/automation.py`](app/services/automation.py) |

## How it works

```
HubSpot (company/contact created) ──signed webhook──▶ /webhooks/hubspot
   verify HMAC v3 → dedupe event → queue job (SQLite) → 200 OK in milliseconds
                                         │
                       background worker ┘──▶ Forager API ──▶ HubSpot CRM API
```

- **Forager client:** typed wrapper over the documented endpoints. It retries with backoff, polls work-email lookups, and counts credits, checking a budget cap before each paid call.
- **Idempotency:** each webhook event is processed once, and only one job per record can be active. Records that already have a `forager_enrichment_status` are skipped, so replays and the service's own contact creations spend no credits.
- **Honest data:** fields Forager doesn't return are left empty, never invented. Records get `enriched` or `partial`, with a note naming what was missing and why.
- **Security:** secrets come only from environment variables. Webhooks are signature-checked, admin endpoints need a key, and logs mask emails, phone numbers and tokens.

## Run locally

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env          # fill in values (see docs/setup.md)
python -m scripts.check_config  # verifies credentials; prints no secrets
python -m scripts.setup_hubspot_properties
uvicorn app.main:app --reload
pytest                          # offline: all external APIs are mocked
```

Operator endpoints (header `X-Admin-Key`): `POST /admin/enrich/company/{id}`,
`POST /admin/enrich/contact/{id}`, `POST /admin/discover` (title-filter
preview), `POST /admin/reconcile`, `GET /admin/jobs`, `GET /admin/credits`.

## Documentation

- [Requirements & acceptance criteria](docs/requirements.md)
- [Architecture](docs/architecture.md)
- [API contracts (verified against the official docs)](docs/api-contracts.md)
- [Field mapping and extra Forager fields to discuss](docs/data-mapping.md)
- [Test plan](docs/test-plan.md) · [Setup](docs/setup.md) · [Deployment (Render)](docs/deployment.md) · [Demo checklist](docs/demo-checklist.md)
- [Task tracker](TASKS.md)
