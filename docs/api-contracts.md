# API Contracts

Status legend: ✅ verified from official docs (date: 2026-10-24) ·
🔎 verified from docs, still to confirm with one live call in Phase 2 ·
⚠️ undocumented or ambiguous. Code must handle every possible behaviour.

---

## 1. Forager

- Docs: https://docs.forager.ai/openapi.md · OpenAPI bundle: https://docs.forager.ai/_bundle/openapi.yaml
- Base URL ✅ `https://api-v2.forager.ai`
- Auth ✅ header `X-API-KEY: <FORAGER_API_KEY>`; `{account_id}` path param = `FORAGER_ACCOUNT_ID` (integer)
  — https://docs.forager.ai/api-overview/authentication.md
- Errors ✅ `401` missing/invalid key, `403` key lacks permission
  — https://docs.forager.ai/api-overview/send-your-first-request.md
- Rate limits ⚠️ not documented, except that the single work-email endpoint "is rate limited for interactive use". Treat `429` as retryable and honour `Retry-After`.
- Pagination ✅ search endpoints accept `page` (integer); responses carry `total_search_results`. ⚠️ Page size undocumented.

### 1.1 Credit costs ✅ — https://docs.forager.ai/api-overview/credit-pricing.md

| Call | Credits |
|------|---------|
| Person detail lookup | 1 |
| Person role search (per page) | 1 |
| Organization search (per page) | 1 |
| Work email lookup | 5 (charged only when found, per endpoint doc) |
| Personal email lookup | 5 (empty result → no charge) |
| Phone lookup | 15 (charged only when a number is returned) |
| Reverse email lookup | 5 |
| `*/totals/` endpoints | ⚠️ "Person role details lookup" lists 1 credit for role-search totals; not free. |
| Autocomplete endpoints | ⚠️ not in pricing table; assumed free, to confirm via balance check. |

### 1.2 Endpoints used

All `POST`, JSON body, unless stated.

| Purpose | Method & path | Request fields we use | Response (fields we read) |
|---------|---------------|-----------------------|---------------------------|
| Credit balance / auth check ✅ | `GET /api/users/current/` | — | `accounts[].id`, `accounts[].subscription.credits_balance` (string) |
| Org autocomplete ✅ | `GET /api/{account_id}/datastorage/autocomplete/organizations/?q=` | `q` (name or domain), `page` | `results[].id` (string), `results[].text` ("Name - domain"), `pagination.more` |
| Organization search ✅ | `/api/{account_id}/datastorage/organization_search/` | `domains[]`, `organization_ids[]`, `linkedin_public_identifiers[]`, `page` | `search_results[]`: `id, name, legal_name, website, domain, domain_rank, logo, description, founded_date, operating_status, employees_range, employees_amount, keywords[].name, location{name, osm_locations[]}, finance_info.revenue, linkedin_info{public_identifier, industry{id,name}, public_profile_url}, addresses[]{street_number, street_name, city, state, postcode, country, summary}, date_updated`; `total_search_results` |
| Person role search ✅ | `/api/{account_id}/datastorage/person_role_search/` | `organization_domains[]`, `role_title` (boolean text query), `role_is_current`, `person_name`, `person_linkedin_public_identifiers[]`, `page` | `search_results[]`: `id, role_title, is_current, start_date, organization{…same as org search…}, person{id, full_name, first_name, last_name, headline, description, location, linkedin_info{public_identifier, public_profile_url}}`; `total_search_results` |
| Person detail ✅ | `/api/{account_id}/datastorage/person_detail_lookup/` | `person_id` **or** `linkedin_public_identifier` (slug from `linkedin.com/in/<slug>/`) | `id, full_name, first_name, last_name, headline, description, skills[].name, location{id, name, osm_locations[]{id, name, place_type}}, linkedin_info{public_identifier, industry, public_profile_url}, roles[]{role_title, is_current, start_date, organization{id, name, domain, linkedin_info{public_identifier, public_profile_url}}}, educations[], certifications[], languages[], …` |
| Reverse lookup by email ✅ | `/api/{account_id}/datastorage/person_detail_reverse_lookup/by_email/` | `email` (required) — from OpenAPI bundle | same as person detail |
| Work email (start) ✅ | `POST /api/v2/{account_id}/datastorage/person_contacts_lookup/work_emails/` | `linkedin_public_identifier` **or** `first_name`+`last_name`+`domain` | **202**: `job_id, status, status_check_url, webhook_url` |
| Work email (poll) ✅ | `GET /api/v2/{account_id}/datastorage/person_contacts_lookup/work_emails/{job_id}/` | — | `status ∈ {queued, running, awaiting_provider, completed, failed}`, `result ∈ {found, not_found}`, `emails[]` ("shortest first, each with its verdict"; OpenAPI declares items as strings with min/max length 2, i.e. likely `[email, verdict]` pairs ⚠️), `error_code ∈ {person_not_found, no_current_employer, input_unresolved, provider_error, expired, internal_error}`, `error_code`, `person_id`. Non-terminal responses include `Retry-After`. Polling is free. |
| Personal email ✅ | `/api/{account_id}/datastorage/person_contacts_lookup/personal_emails/` | `person_id` or `linkedin_public_identifier` | list of `{email, email_type, validation_status ∈ valid/risky/invalid/unknown}`; ⚠️ "200 OK with an empty body" when none |
| Phone ✅ | `/api/{account_id}/datastorage/person_contacts_lookup/phone_numbers/` | `person_id` or `linkedin_public_identifier`; optional `quality_tier ∈ {highest_quality (default), most_coverage}` | list of `{phone_number}` (recipe example: `[{"phone_number": "+14155552671"}]`); ⚠️ empty-result shape undocumented |

### 1.3 Forager ambiguities to handle defensively

- ⚠️ `location.osm_locations[].place_type` values are not enumerated. Mapping uses them when present and falls back to splitting `location.name` ("City, State, Country").
- ⚠️ Shape of `emails[]` items in work-email poll is self-contradictory in the OpenAPI bundle. The client accepts strings, `[email, verdict]` pairs and `{email, verdict}` objects, prefers a valid verdict, and skips invalid ones.
- Phone and personal-email responses are JSON **arrays** (OpenAPI bundle). Only `200`/`202` responses are documented; the client treats `401/403` as auth errors, `404` or an empty body as "not found", and other non-2xx responses as errors.
- ⚠️ Empty bodies (`""`, `null`, `[]`) on contact lookups are all treated as "not found".
- ⚠️ Doc text calls the person slug "LinkedIn organization Public identifier" (copy-paste in docs); the path pattern `linkedin.com/in/<slug>/` is authoritative.
- `role_title` "supports a boolean text search query". The exact syntax is not specified. Third-party wrappers report that multi-word terms must be double-quoted. We emit `"Head of Sales" OR "VP"` and confirm in Phase 2 with one call.

---

## 2. HubSpot

- Auth ✅ static access token of the **project-based app** `Forager Enrichment` (app id 58454528, portal 247782088, platform 2026.09): `Authorization: Bearer <HUBSPOT_ACCESS_TOKEN>`. Verified with a live read (`scripts/check_config.py`).
- This portal has **no legacy apps**. Service keys work for REST but [cannot receive webhooks](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/account-service-keys), so the project-based app is required.
- Rate limits 🔎 private apps share per-portal burst limits (tier-dependent); Search API has a lower per-second limit. Client retries `429` with `Retry-After`/backoff.

### 2.1 CRM endpoints 🔎

| Purpose | Method & path |
|---------|---------------|
| Get object | `GET /crm/v3/objects/{companies\|contacts}/{id}?properties=a,b,c` |
| Update object | `PATCH /crm/v3/objects/{type}/{id}` body `{"properties": {...}}` |
| Create object | `POST /crm/v3/objects/{type}` body `{"properties": {...}, "associations": [...]}` |
| Search | `POST /crm/v3/objects/{type}/search` body `{"filterGroups":[{"filters":[{"propertyName","operator":"EQ","value"}]}], "properties":[...], "limit"}` |
| List associations | `GET /crm/v4/objects/companies/{id}/associations/contacts` |
| Create with association | contact → company uses `HUBSPOT_DEFINED` type id `1` (primary company) |
| Associate (default) | `PUT /crm/v4/objects/contacts/{contactId}/associations/default/companies/{companyId}` |
| Read/create properties | `GET/POST /crm/v3/properties/{type}`; groups `POST /crm/v3/properties/{type}/groups` |

Reference: https://developers.hubspot.com/docs/api-reference/crm-companies-v3/guide,
https://developers.hubspot.com/docs/api-reference/crm-associations-v4/guide,
https://developers.hubspot.com/docs/api-reference/crm-properties-v3/guide

Required scopes 🔎: `crm.objects.companies.read/write`, `crm.objects.contacts.read/write`,
`crm.schemas.companies.write`, `crm.schemas.contacts.write` (create custom properties).

### 2.2 Webhooks ✅

Source: https://developers.hubspot.com/docs/apps/developer-platform/add-features/configure-webhooks,
https://developers.hubspot.com/docs/api-reference/legacy/webhooks/guide

- Subscriptions are declared in `hubspot-project/src/app/webhooks/webhooks-hsmeta.json` (`crmObjects`: `object.creation` for `company` and `contact`) and deployed with `hs project upload`. `targetUrl` must be publicly reachable; subscriptions stay `active: false` until the Railway URL exists.
- Target URL receives `POST` with a JSON **array** of events; ≤ 100 events per request; ≤ 10 concurrent requests per app.
- Retries: on connection failure, response > **5 s**, or any 4xx/5xx — up to **10 retries over 24 h**.
- Legacy event fields: `eventId, subscriptionId, portalId, appId, occurredAt, subscriptionType` (e.g. `contact.creation`, `company.creation`), `attemptNumber` (starts at 0), `objectId, changeSource, changeFlag`. ⚠️ The guide's sample uses `eventType` in one place; the parser accepts both.
- Generic format (**expected for our `crmObjects` subscriptions**): `subscriptionType: "object.creation"` with `objectTypeId` (`0-1` contacts, `0-2` companies). Parser supports both.

### 2.3 Webhook signature ✅

Source: https://developers.hubspot.com/docs/apps/legacy-apps/authentication/validating-requests

- Secret: the app's **client secret** (Development → Projects → forager-enrichment → app → Auth tab) → env `HUBSPOT_CLIENT_SECRET`. Source for v3 on the new platform: https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/request-validation
- **v3**: headers `X-HubSpot-Signature-v3`, `X-HubSpot-Request-Timestamp` (ms).
  `base64(HMAC_SHA256(secret, method + uri + body + timestamp))`, where `uri` is the full public URL with the documented percent-decodings applied. Reject if the timestamp is older than 5 minutes. Compare in constant time.
- **v1** (CRM webhook events): header `X-HubSpot-Signature` = `hex(SHA256(client_secret + body))`, `X-HubSpot-Signature-Version: v1`.
- ⚠️ Which version project-app webhooks send is not stated (v3 expected). We verify v3 when its headers are present, otherwise v1, and log which version was used. Behind Railway's proxy the URI must be rebuilt from `PUBLIC_BASE_URL` (not the internal host/scheme).
