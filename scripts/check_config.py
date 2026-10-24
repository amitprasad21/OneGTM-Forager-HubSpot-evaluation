"""Verify configuration and credentials without printing secret values.

Makes only free, read-only calls:
- Forager  GET /api/users/current/          (no credits)
- HubSpot  GET /crm/v3/objects/companies    (limit=1)
- HubSpot  GET /crm/v3/properties/{type}    (checks default properties we map to)

Usage: python -m scripts.check_config
"""

import sys

import httpx

from app.config import settings

FORAGER_BASE_URL = "https://api-v2.forager.ai"
HUBSPOT_BASE_URL = "https://api.hubapi.com"

EXPECTED_PROPERTIES = {
    "companies": [
        "name", "domain", "website", "description", "annualrevenue",
        "numberofemployees", "founded_year", "linkedin_company_page",
        "city", "state", "country", "zip", "address",
    ],
    "contacts": [
        "firstname", "lastname", "email", "phone", "jobtitle", "company",
        "city", "state", "country", "hs_linkedin_url",
    ],
}


def report_settings() -> bool:
    fields = {
        "FORAGER_API_KEY": settings.forager_api_key.get_secret_value(),
        "FORAGER_ACCOUNT_ID": settings.forager_account_id,
        "HUBSPOT_ACCESS_TOKEN": settings.hubspot_access_token.get_secret_value(),
        "HUBSPOT_CLIENT_SECRET": settings.hubspot_client_secret.get_secret_value(),
    }
    ok = True
    for name, value in fields.items():
        print(f"{name}: {'set' if value else 'MISSING'} (len={len(value)})")
        ok = ok and bool(value)
    return ok


def check_forager(client: httpx.Client) -> bool:
    response = client.get(
        f"{FORAGER_BASE_URL}/api/users/current/",
        headers={"X-API-KEY": settings.forager_api_key.get_secret_value()},
    )
    print(f"Forager /api/users/current/: HTTP {response.status_code}")
    if response.status_code != 200:
        return False
    accounts = response.json().get("accounts", [])
    match = next(
        (a for a in accounts if str(a.get("id")) == settings.forager_account_id),
        None,
    )
    print(f"Forager account id matches FORAGER_ACCOUNT_ID: {match is not None}")
    if match:
        balance = (match.get("subscription") or {}).get("credits_balance")
        print(f"Forager credits_balance: {balance}")
    return match is not None


def check_hubspot(client: httpx.Client) -> bool:
    headers = {"Authorization": f"Bearer {settings.hubspot_access_token.get_secret_value()}"}
    response = client.get(
        f"{HUBSPOT_BASE_URL}/crm/v3/objects/companies",
        params={"limit": 1},
        headers=headers,
    )
    print(f"HubSpot companies read: HTTP {response.status_code}")
    ok = response.status_code == 200

    for object_type, expected in EXPECTED_PROPERTIES.items():
        response = client.get(
            f"{HUBSPOT_BASE_URL}/crm/v3/properties/{object_type}",
            headers=headers,
        )
        print(f"HubSpot {object_type} properties read: HTTP {response.status_code}")
        if response.status_code != 200:
            ok = False
            continue
        existing = {p["name"] for p in response.json().get("results", [])}
        missing = [name for name in expected if name not in existing]
        print(f"  missing default properties: {missing or 'none'}")
        custom = sorted(name for name in existing if name.startswith("forager_"))
        print(f"  forager_* properties present: {len(custom)}")
    return ok


def main() -> int:
    settings_ok = report_settings()
    with httpx.Client(timeout=20) as client:
        forager_ok = check_forager(client)
        hubspot_ok = check_hubspot(client)
    print(f"RESULT settings={settings_ok} forager={forager_ok} hubspot={hubspot_ok}")
    return 0 if settings_ok and forager_ok and hubspot_ok else 1


if __name__ == "__main__":
    sys.exit(main())
