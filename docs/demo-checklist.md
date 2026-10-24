# Demo & Submission Checklist

Service: https://forager-hubspot-enrichment-oxqc.onrender.com ·
Repo: https://github.com/amitprasad21/OneGTM-Forager-HubSpot-evaluation

## Credit budget for the recording (paid Forager key)

| Segment | Credits |
|---------|---------|
| OpenAI company webhook: org search 1 + people search 1 + 5 × (work email 5 + phone 15) | ≈ 102 |
| Title-filter previews ×2 | 2 |
| Contact webhook demo: people search 1 + work email 5 + phone 15 | ≈ 21 |
| **Total** | **≈ 125** |

Email/phone are charged only when found, so the real spend is usually lower.

## Before recording (do not create the OpenAI company yet)
- [ ] `python -m scripts.admin credits` (with `SERVICE_URL` in `.env`) shows budget ≥ 125. Needs the paid key in Render.
- [ ] `python -m scripts.admin health` shows `"status": "ok"`.
- [ ] cron-job.org "alive" job is green.
- [ ] HubSpot has **no** existing OpenAI company or contacts.
- [ ] In HubSpot → Companies and → Contacts, add the `Forager enrichment status` column (table header **+**).
- [ ] Tabs open: (1) HubSpot Companies, (2) HubSpot Contacts, (3) Render → service → **Logs**, (4) GitHub repo, (5) terminal in the repo with the venv active.
- [ ] Terminal font large; `.env` closed in the editor. Never open `.env` on screen.

## Recording script (≈ 7–8 min)

**1. Intro (30 s).** Tab: GitHub README.
> "This is a Python service that enriches HubSpot companies and contacts with Forager, triggered live by HubSpot webhooks. It's FastAPI on Render, with signed webhooks, a background job queue, and secrets only in environment variables."

Scroll the requirement → file table.

**2. Architecture & code (1 min).** Tab: GitHub.
- `docs/architecture.md` diagram: webhook → verify signature → queue → worker → Forager → HubSpot.
- `app/webhooks.py`: "HMAC v3 signature check with a 5-minute replay window."
- `app/title_filter.py`: "Forager boolean title query, plus a strict local re-check: exclude always wins."
- `app/services/automation.py`, `company_created`: "Enrich the company; enrich existing contacts, or discover new ones if there are none."

**3. Tests (30 s).** Terminal:
```
pytest -q
```
> "236 tests, fully offline. Forager and HubSpot are mocked, so the suite never spends credits."

**4. Company webhook: OpenAI (2 min).** This is the primary deliverable.
- Tab: Render Logs (leave visible in a split screen if possible).
- Tab: HubSpot → Companies → **Create company**: Name `OpenAI`, Company domain `openai.com` → **Create**.
- Render Logs, point out in order:
  - `webhook.accepted` with `signature_version: v3`: "HubSpot called us; signature verified; acknowledged in milliseconds."
  - `job.started company_created`
  - `company.enriched`
  - `discovery.candidates` with `kept_titles` / `filtered_titles`: "the title filter at work."
  - `discovery.contact_created` ×5, then `job.done`
- Back in HubSpot (refresh) → OpenAI company: description, annual revenue, employees, LinkedIn page, city/state/country, Forager status `Enriched`.
- Company → **Contacts** card: 5 associated contacts. Open each: name, job title, LinkedIn URL, company domain + company LinkedIn URL, email, phone, city/state/country.
> "Anything Forager doesn't have is left empty and named in the enrichment notes. Nothing is invented."

**5. Title filtering (1 min).** Terminal:
```
python -m scripts.admin discover openai.com --include "Engineer"
python -m scripts.admin discover openai.com --include "VP" "Head" "Director" --exclude "Assistant"
```
> "Same company, different title filters, different people. The admin key is read from the environment, never typed."

**6. Contact webhook (1 min).**
- Pick one **Engineer** from step 5 who is *not* already in HubSpot.
- HubSpot → Contacts → **Create contact**: First name, Last name; associate company **OpenAI** → **Create**.
- Render Logs: `webhook.accepted` → `job.started contact_created` → `contact.enriched`.
- Refresh the contact: title, LinkedIn, location, email, phone filled in.

**7. Reliability & security (45 s).** Terminal:
```
curl.exe -s -o NUL -w "%{http_code}\n" -X POST https://forager-hubspot-enrichment-oxqc.onrender.com/webhooks/hubspot -d "[]"
python -m scripts.admin jobs
python -m scripts.admin credits
```
> "Unsigned requests get 401. Every event is processed once, and records that already have a status are skipped, so retries and our own created contacts cost zero credits. Credits are tracked against a budget and capped by the live Forager balance."

**8. Extra fields for discussion (30 s).** Tab: GitHub `docs/data-mapping.md` §4:
> "Forager also returns headline, the LinkedIn About text, skills, role history, education, funding and hiring signals. They're behind a flag for discussion, not silently added."

## After recording: submission
- [ ] Video link
- [ ] Live URL: https://forager-hubspot-enrichment-oxqc.onrender.com
- [ ] Repo: https://github.com/amitprasad21/OneGTM-Forager-HubSpot-evaluation (grant reviewers access if private)
- [ ] HubSpot: OpenAI company + 5 contacts (reviewer access or screenshots)
- [ ] Notes: extra Forager fields + any fields Forager could not supply (data-mapping §4)
