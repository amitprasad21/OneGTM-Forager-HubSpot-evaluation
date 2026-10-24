# Deployment (Railway)

## 1. Prerequisites
- Local test suite green (`pytest`).
- Repository pushed to GitHub (Railway deploys from a repo or via `railway up`).

## 2. Service configuration

| Item | Value |
|------|-------|
| Builder | Railpack/Nixpacks auto-detects Python from `requirements.txt` |
| Python version | pinned via `.python-version` (`3.13`) |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"` (also in `railway.json`) |
| Health check path | `/health` |
| Replicas | **1**. The SQLite queue and idempotency store assume a single instance. |
| Volume | mount at `/data`; set `DATABASE_PATH=/data/app.db`. Without a volume, jobs and dedupe state are lost on redeploy. |

## 3. Environment variables
Set every variable from [setup.md §3](setup.md) in Railway → service →
**Variables**. Never commit them. `PUBLIC_BASE_URL` = the Railway public domain
(Settings → Networking → Generate Domain), with no trailing slash.

## 4. HubSpot webhook subscriptions
1. Edit `hubspot-project/src/app/webhooks/webhooks-hsmeta.json`:
   - `settings.targetUrl` → `https://<railway-domain>/webhooks/hubspot`
   - set both `object.creation` subscriptions (company, contact) to `"active": true`
2. `cd hubspot-project && hs project upload`, then commit the change.
3. Create a test record in HubSpot; Railway logs should show `webhook.accepted`.
   Delivery history: Development → Projects → forager-enrichment → app → Monitoring.

## 5. Verification checklist

| Check | How | Expected |
|-------|-----|----------|
| Health | `curl https://<domain>/health` | `{"status":"ok", ... true}` |
| Signature | HubSpot test event | 200; log shows `signature_version` |
| Bad signature | `curl -X POST .../webhooks/hubspot -d '[]'` | 401 |
| Company flow | create a company in HubSpot | enriched within ~1 min; contacts discovered if none |
| Contact flow | create a contact | enriched |
| Duplicate | replay the same event | one job, no extra credits |
| Logs | Railway logs | no tokens/emails/phones |

## 6. Rollback
Railway → Deployments → previous deployment → **Redeploy**.
