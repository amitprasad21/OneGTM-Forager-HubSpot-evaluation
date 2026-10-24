# Local Setup

## 1. Prerequisites

- Python 3.12+ (developed on 3.14; Railway pinned in [deployment.md](deployment.md))
- Git
- A Forager account and a HubSpot account (free tiers are enough)

## 2. Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
copy .env.example .env   # then fill in values
```

> Note: on Windows PowerShell, `pip freeze > requirements.txt` writes UTF-16,
> which pip on Linux (Railway) cannot read. Use
> `pip freeze | Out-File -Encoding utf8 requirements.txt`, or edit by hand.

## 3. Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FORAGER_API_KEY` | yes | Forager API key (app.forager.ai → API) |
| `FORAGER_ACCOUNT_ID` | yes | Integer account id used in Forager URL paths |
| `HUBSPOT_ACCESS_TOKEN` | yes | Static access token of the HubSpot project app |
| `HUBSPOT_CLIENT_SECRET` | yes (webhooks) | Project app client secret, used to verify webhook signatures |
| `PUBLIC_BASE_URL` | yes (webhooks) | Public https base URL, e.g. `https://<app>.up.railway.app`. Needed to rebuild the signed URI |
| `ADMIN_API_KEY` | yes | Random string protecting `/admin/*` |
| `DATABASE_PATH` | no | SQLite file (default `./data/app.db`) |
| `FORAGER_CREDIT_BUDGET` | no | Hard cap on credits this deployment may spend (default 45 — the account has 50) |
| `DISCOVERY_TITLES` | no | Default include titles, comma-separated |
| `DISCOVERY_EXCLUDE_TITLES` | no | Default exclude titles |
| `DISCOVERY_MAX_CONTACTS` | no | Default 5 |
| `ENABLE_PHONE_LOOKUP` / `ENABLE_PERSONAL_EMAIL_LOOKUP` | no | Toggle expensive lookups (default true / true) |
| `ENRICH_EXTRA_FIELDS` | no | Write nice-to-have fields (default false) |
| `LOG_LEVEL` | no | default `INFO` |

## 4. External account configuration

### Forager
1. Sign up at https://app.forager.ai, then open the **API** section and create a key.
2. Find your account id: it appears in API URLs. You can also confirm it with
   `GET https://api-v2.forager.ai/api/users/current/` → `accounts[].id`.
3. Verify without exposing the secret: `python -m scripts.check_config`
   prints presence/length of each variable, HTTP statuses and the credit balance — never values.

### HubSpot project-based app
New HubSpot accounts have no legacy private apps, and service keys cannot receive
webhooks, so the app lives in [hubspot-project/](../hubspot-project/) (static auth,
private distribution, scopes in `src/app/app-hsmeta.json`).
1. Install the CLI: `npm install -g @hubspot/cli` (Node 18+).
2. `hs account auth` → generate a personal access key in the browser → paste it.
3. `cd hubspot-project && hs project upload --force-create`.
4. HubSpot → **Development → Projects → forager-enrichment → app → Distribution** →
   **Install now** under Standard install, then **Show** → copy the token → `HUBSPOT_ACCESS_TOKEN`.
5. **Auth** tab → client secret → `HUBSPOT_CLIENT_SECRET`.
6. Run `python -m scripts.setup_hubspot_properties` once to create the `forager_*` custom properties.
7. Webhooks are activated after deployment (see deployment.md §4).

## 5. Run & test

```powershell
uvicorn app.main:app --reload
pytest                       # offline, no credentials needed
$env:RUN_LIVE_TESTS=1; pytest -m live   # spends Forager credits
```

## 6. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `401` from Forager | wrong `FORAGER_API_KEY`, or the key is missing from the header |
| `404` from Forager | wrong `FORAGER_ACCOUNT_ID` |
| HubSpot `403 MISSING_SCOPES` | add the scope to `app-hsmeta.json`, `hs project upload`, reinstall, re-copy the token |
| HubSpot `400 PROPERTY_DOESNT_EXIST` | run `scripts.setup_hubspot_properties` |
| Webhook `401 invalid signature` | wrong client secret, or `PUBLIC_BASE_URL` doesn't match the subscribed target URL exactly (scheme, host, path, trailing slash) |
| pip on Railway: `invalid requirement '\xff\xfe…'` | requirements.txt is UTF-16; re-save as UTF-8 |
