# Requirements & Acceptance Criteria

Source: *ONEGTM LAB — AI Automation Engineer Evaluation Task* (PDF, 2 pages).
Everything below is derived from that document. Items marked **[Decision]** are
our interpretation where the PDF is silent; items marked **[Open]** need input.

## 1. Functional requirements

| ID | Requirement (PDF wording, condensed) | Acceptance criteria |
|----|--------------------------------------|---------------------|
| R1 | **Enrich companies** — pull full company details (description, revenue, headcount, etc.). | Given a HubSpot company with a domain, the service writes description, annual revenue, employee count, industry, founded year, website, company LinkedIn URL, HQ city/state/country (whatever Forager returns) to that company. Fields Forager does not return are left untouched, never fabricated. |
| R2 | **Enrich contacts** — fill the required contact fields (§2). | Given a HubSpot contact identifiable by LinkedIn URL, email, or name + company domain, the service writes every §2 field Forager returns. Missing data is recorded in an enrichment-status note, not invented. |
| R3 | **Find contacts at a company** with job-title filtering. | Given a company domain and a title filter (include/exclude terms), the service returns only current employees whose title matches the filter; the filter is configurable per call and via env default. A test proves non-matching titles are excluded. |
| R4 | **Company webhook** — on company creation: enrich the company; if contacts exist in HubSpot enrich them, otherwise find them. | A `company.creation` (or generic `object.creation` for companies) event results in: company enriched; associated contacts enriched **or**, when none are associated, up to *N* title-filtered contacts discovered, created, associated, and enriched. |
| R5 | **Contact webhook** — on contact creation: enrich that contact. | A `contact.creation` event results in that contact being enriched. Contacts the service itself created (R4 discovery) are not enriched twice. |

## 2. Required fields per enriched contact

| Field | Required | Notes |
|-------|----------|-------|
| First name, last name | Yes | |
| Person LinkedIn URL | Yes | |
| Job title | Yes | Current role |
| Employer name, domain, company LinkedIn URL | Yes | From current role's organization |
| Email | If available | Work email preferred; personal email fallback **[Decision]** |
| Phone | If available | |
| City, state, country | Yes | Parsed from Forager location data |
| Person description / LinkedIn "About" | Nice-to-have | **Flag for discussion; not written to HubSpot by default** (feature flag) |

## 3. Required fields per enriched company

"Full details including description, revenue, headcount, etc." — see
[data-mapping.md](data-mapping.md) for the concrete list.

## 4. Engineering requirements

- Python, custom code; no n8n / no-code tools.
- Deployed live (Railway default) so webhooks run.
- Secrets only in environment variables; never hard-coded or logged.
- Clean, production-quality code.
- Title-based filtering demonstrably works.

## 5. Primary deliverable (highest priority)

- [ ] OpenAI (dummy/test) company in HubSpot, enriched with all available details.
- [ ] 5 people under it, enriched with email, phone, city, state, country.
- [ ] Records look complete and clean.

If Forager cannot provide 5 people with both email and phone, we report the
shortfall honestly and pick the most complete candidates; we never fabricate.

## 6. Submission

1. Video: enrichment running, webhook firing, records populating, title filtering.
2. Live service URL + Git repository.
3. Completed OpenAI records in HubSpot.
4. Notes on interesting extra Forager fields ([data-mapping.md §4](data-mapping.md)).

## 7. Constraints & risks

| Constraint | Impact |
|-----------|--------|
| Forager free tier: PDF says 150 credits, **account actually received 50** (balance log: "Initial demo credits 50.00", 2026-10-24) | Cheapest full enrichment: 1 org search + 1 role search (returns name, LinkedIn, title, employer, location for many people) + per person 5 (work email) + 15 (phone), charged only when found → 5 people ≈ **102 credits**. 50 credits cover company + 5 emails + ~1 phone. Little room for re-runs → unit tests never hit live APIs; live runs are gated and logged; a credit-budget guard caps spend. |
| HubSpot retries webhooks that take > 5 s | Webhook must ack fast; enrichment runs in the background. |
| HubSpot retries up to 10× over 24 h | Processing must be idempotent per event and per object. |
| Service-created contacts emit `contact.creation` | Loop/double-spend prevention required (R5). |

## 8. Open questions

- **[Open]** Should the nice-to-have fields (headline, About, skills) be written to HubSpot? Default: off, documented in data-mapping §4.
- **[Decided 2026-10-24]** Credit gap: stay within the 50 credits. Phone lookups for **2** of the 5 OpenAI contacts; work emails for as many as the remaining budget allows (≈ 3, more if some lookups return nothing and are not charged). The shortfall is reported in the submission notes.
- **[Open]** Default title filter for discovery. Proposed: leadership & GTM roles (`CEO, CTO, COO, VP, Head, Director, Chief`), max 5 contacts.
