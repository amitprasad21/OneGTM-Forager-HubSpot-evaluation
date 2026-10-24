# Deployment (Render)

Target: **Render Free web service + external keep-alive** (decided 2026-10-24).
Source: https://render.com/docs/free, https://render.com/docs/python-version

## 1. Free-plan constraints and how the design handles them

| Render Free behaviour (from Render docs) | Impact | Mitigation |
|------------------------------------------|--------|------------|
| Spins down after **15 min** without inbound traffic; spin-up takes **about one minute** | HubSpot times out after 5 s and retries later, so demos would be slow | External pinger calls `GET /health` every 10 min (§5) |
| **Ephemeral filesystem**, no persistent disk on Free | SQLite (job queue, event dedupe, credit ledger) is lost on redeploy/restart | HubSpot `forager_enrichment_status` is the durable idempotency guard; credit budget is capped by Forager's live balance at startup; `POST /admin/reconcile` re-queues records left without a status |
| 750 free instance hours per workspace per month | One always-on service ≈ 744 h | Keep only this service on Free in the workspace |

Upgrade path: Starter plan + persistent disk mounted at `/var/data`
(`DATABASE_PATH=/var/data/app.db`) makes the SQLite queue durable without code changes.

## 2. Prerequisites
- Local test suite green (`pytest`).
- Repository pushed to GitHub (Render deploys from a connected repo).

## 3. Service configuration ([render.yaml](../render.yaml) blueprint)

| Item | Value |
|------|-------|
| Runtime | Python, version from `.python-version` (`3.14`, matching local development) |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"` |
| Health check path | `/health` |
| Instances | **1** (SQLite queue assumes a single instance) |
| `DATABASE_PATH` | `/tmp/app.db` (ephemeral on Free) |
| Credit settings | Defaults (budget cap 500, lowered to the live Forager balance at startup; no per-job phone limit). Override via env only if needed. |

Create it with Render Dashboard → **New → Blueprint** → select the repo
(reads `render.yaml`), or **New → Web Service** with the values above.

## 4. Environment variables
Set every variable from [setup.md §3](setup.md) in Render → service →
**Environment**. Secrets are declared `sync: false` in `render.yaml`, so Render
asks for them on first deploy and never reads them from the repo.
The webhook URL used for signature checks comes from Render's default
`RENDER_EXTERNAL_URL` ("the service's full `onrender.com` URL", per
https://render.com/docs/environment-variables), so `PUBLIC_BASE_URL` is only
needed for a custom domain.

## 5. Keep-alive
Create a free job at https://cron-job.org (or UptimeRobot) that requests
`https://<service>.onrender.com/health` every **10 minutes**. `/health` is cheap
and makes no external API calls.

## 6. HubSpot webhook subscriptions
1. Edit `hubspot-project/src/app/webhooks/webhooks-hsmeta.json`:
   - `settings.targetUrl` → `https://<service>.onrender.com/webhooks/hubspot`
   - set both `object.creation` subscriptions (company, contact) to `"active": true`
2. `cd hubspot-project && hs project upload`, then commit the change.
3. Create a test record in HubSpot; Render logs should show `webhook.accepted`.
   Delivery history: Development → Projects → forager-enrichment → app → Monitoring.

## 7. Verification checklist

| Check | How | Expected |
|-------|-----|----------|
| Health | `curl https://<service>.onrender.com/health` | `{"status":"ok", ... true}` |
| Signature | HubSpot test event | 200; log shows `signature_version` |
| Bad signature | `curl -X POST .../webhooks/hubspot -d '[]'` | 401 |
| Company flow | create a company in HubSpot | enriched within ~1 min; contacts discovered if none |
| Contact flow | create a contact | enriched |
| Duplicate | replay the same event | no duplicate contacts, no extra credits |
| Keep-alive | cron-job.org history | 200 every 10 min |
| Logs | Render → Logs | no tokens/emails/phones |

## 8. Rollback
Render → service → **Events** → pick a previous deploy → **Rollback**.
