# Data Mapping: Forager → HubSpot

Rules:
- Only write a property when Forager returned a non-empty value. Never overwrite with blanks, never invent.
- HubSpot **default** property names marked 🔎 were confirmed to exist in portal 247782088 by `scripts/check_config.py` (2026-10-24).
- Custom properties live in a property group **`forager_enrichment`** and use the prefix `forager_`. They are created idempotently by `scripts/setup_hubspot_properties.py` (run 2026-10-24: 10 company + 7 contact properties). Discussion fields (`forager_headline`, `forager_about`, `forager_skills`) are only created with `--include-extra-fields`.
- Enumeration-type defaults (e.g. company `industry`) are **not** written, because a value outside HubSpot's fixed options fails validation. Raw values go to custom text properties instead.

## 1. Company (Forager `organization_search` result → HubSpot company)

| Forager field | HubSpot property | Type | Notes |
|---------------|------------------|------|-------|
| `name` | `name` 🔎 | default | only if HubSpot value empty |
| `domain` | `domain` 🔎 | default | only if empty |
| `website` | `website` 🔎 | default | |
| `description` | `description` 🔎 | default | |
| `finance_info.revenue` | `annualrevenue` 🔎 | default number | USD assumed ⚠️ (currency undocumented) |
| `employees_amount` | `numberofemployees` 🔎 | default number | |
| `employees_range` | `forager_employees_range` | custom text | e.g. "1001-5000" |
| `founded_date` | `founded_year` 🔎 | default text | year part only |
| `linkedin_info.public_profile_url` | `linkedin_company_page` 🔎 | default | |
| `linkedin_info.industry.name` | `forager_industry` | custom text | not the enum `industry` |
| `keywords[].name` | `forager_keywords` | custom textarea | comma-joined, max 20 |
| `operating_status` | `forager_operating_status` | custom text | |
| `legal_name` | `forager_legal_name` | custom text | |
| `logo` | `forager_logo_url` | custom text | |
| `addresses[0].city/state/country/postcode` | `city`, `state`, `country`, `zip` 🔎 | default | HQ = first address ⚠️ (ordering undocumented); falls back to `location` |
| `addresses[0].street_number + street_name` | `address` 🔎 | default | |
| `id` | `forager_organization_id` | custom text | |
| — | `forager_enrichment_status` | custom enum | `in_progress / enriched / partial / not_found / failed` |
| — | `forager_enriched_at` | custom datetime | |
| — | `forager_enrichment_notes` | custom textarea | missing fields, errors (no PII) |

## 2. Contact (Forager person detail + contact lookups → HubSpot contact)

| Required field | Forager source | HubSpot property |
|----------------|----------------|------------------|
| First name | `first_name` | `firstname` 🔎 |
| Last name | `last_name` | `lastname` 🔎 |
| Person LinkedIn URL | `linkedin_info.public_profile_url` | `hs_linkedin_url` ✅ (exists in this portal) |
| Job title | current role (`roles[is_current]`, most recent `start_date`) `.role_title` | `jobtitle` 🔎 |
| Employer name | current role `.organization.name` | `company` 🔎 |
| Employer domain | current role `.organization.domain` | `forager_company_domain` (custom) |
| Employer LinkedIn URL | current role `.organization.linkedin_info.public_profile_url` | `forager_company_linkedin_url` (custom) |
| Email | work-email job `emails[]` (valid preferred) → personal email (`validation_status=valid`) | `email` 🔎 (only if empty; else `forager_alt_email`) |
| Phone | phone lookup `[0].phone_number` | `phone` 🔎 |
| City / State / Country | `location.osm_locations[place_type]`, fallback split of `location.name` | `city`, `state`, `country` 🔎 |
| — | `id` | `forager_person_id` (custom) |
| — | — | `forager_enrichment_status`, `forager_enriched_at`, `forager_enrichment_notes` |

Contacts are associated with their HubSpot company (default association).

## 3. Identity matching (duplicate prevention)

| Object | Match keys, in order |
|--------|----------------------|
| Company | HubSpot record id (from webhook) → Forager by `domain` → by name autocomplete |
| Contact (existing) | `forager_person_id` → LinkedIn URL → `email` |
| Contact (discovered, before create) | search HubSpot by `forager_person_id`, then LinkedIn URL, then email; skip if found |

## 4. Extra Forager fields — FOR DISCUSSION (not written by default)

Available in person detail / org search responses; gated behind
`ENRICH_EXTRA_FIELDS=false`:

| Field | Value for sales | Concern |
|-------|-----------------|---------|
| `headline` | Quick positioning line | Low |
| `description` (LinkedIn "About") | Personalisation, talk tracks | Long text; PII/GDPR considerations |
| `skills[].name` | Persona targeting | Noisy |
| `roles[]` history / tenure (`start_date`, `duration`) | "New in role" triggers | Volume |
| `educations[]`, `certifications[]`, `languages[]` | Rapport, qualification | PII |
| `photo` | CRM avatar | Licensing |
| Org `found_funding_events`, `found_job_post_events` | Buying signals (hiring, funding) | Extra filters/credits |
| Org `domain_rank`, web technologies (`website_detail_lookup`, 1 credit) | Tech-stack targeting | Extra credit |
| Phone `quality_tier=most_coverage` | More numbers reachable | Different pricing |

Final notes on what Forager actually returned for the OpenAI records will be
appended here after Phase 7.
