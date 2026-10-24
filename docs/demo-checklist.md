# Demo & Submission Checklist

## Before recording
- [ ] Railway service healthy (`/health` all true)
- [ ] HubSpot webhooks active (company created, contact created)
- [ ] Enough Forager credits left for a live demo contact (≥ 21), or demo a contact-less path
- [ ] OpenAI company + 5 contacts already complete (primary deliverable)
- [ ] Browser tabs: HubSpot companies, HubSpot contacts, Railway logs, GitHub repo, terminal

## Video script (≈ 5–7 min)
1. **Context (30 s):** goal, stack (Python/FastAPI on Railway), architecture diagram from `docs/architecture.md`.
2. **Code tour (1 min):** clients, mapping, title filter, webhook verification, job queue; secrets in env only.
3. **Tests (30 s):** run `pytest`. All offline and green.
4. **Company webhook (1.5 min):** create a test company in HubSpot → Railway logs show `webhook.accepted` → job → company fields populate → contacts discovered and associated.
5. **Contact webhook (1 min):** create a contact with a LinkedIn URL → enriched fields appear.
6. **Title filtering (1 min):** `POST /admin/discover` with two different title filters → different, filtered results.
7. **OpenAI records (1 min):** walk through the company and the 5 contacts. Point out email, phone, city/state/country, and flag any honestly-missing values.
8. **Reliability (30 s):** duplicate event replay → no duplicates; bad signature → 401.
9. **Extra fields (30 s):** data-mapping §4 discussion items.

## Submission
- [ ] Video link
- [ ] Live URL: `https://<railway-domain>`
- [ ] Git repository URL (access granted to reviewers)
- [ ] HubSpot: OpenAI company + 5 contacts (reviewer access / screenshots)
- [ ] Notes on extra Forager fields + data limitations (data-mapping §4)
