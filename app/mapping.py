"""Pure Forager -> HubSpot property mapping. Rules: docs/data-mapping.md."""

from urllib.parse import urlparse

MAX_KEYWORDS = 20

CITY_PLACE_TYPES = {"city", "town", "village", "municipality", "hamlet", "locality"}
STATE_PLACE_TYPES = {"state", "region", "province", "county", "state_district"}
COUNTRY_PLACE_TYPES = {"country"}


def normalize_domain(value: str | None) -> str | None:
    """Reduce a domain or URL to a bare lowercase host without 'www.'."""
    if not value or not value.strip():
        return None
    value = value.strip().lower()
    host = urlparse(value if "://" in value else f"//{value}").hostname or ""
    host = host.removeprefix("www.")
    return host or None


def parse_location(location: dict | None) -> tuple[str | None, str | None, str | None]:
    """Return (city, state, country) from a Forager InnerLocation.

    Uses osm_locations place types when present, otherwise splits the display
    name: 'City, State, Country' or 'City, Country' or 'Country'.
    """
    if not isinstance(location, dict):
        return None, None, None

    city = state = country = None
    for place in location.get("osm_locations") or []:
        place_type = (place.get("place_type") or "").lower()
        name = place.get("name") or None
        if place_type in CITY_PLACE_TYPES:
            city = city or name
        elif place_type in STATE_PLACE_TYPES:
            state = state or name
        elif place_type in COUNTRY_PLACE_TYPES:
            country = country or name
    if city or state or country:
        return city, state, country

    parts = [part.strip() for part in (location.get("name") or "").split(",") if part.strip()]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[-1]
    if len(parts) == 2:
        return parts[0], None, parts[1]
    if len(parts) == 1:
        return None, None, parts[0]
    return None, None, None


def map_company(org: dict) -> dict[str, str]:
    """Map a Forager organization to HubSpot company properties (non-empty values only)."""
    finance = org.get("finance_info") or {}
    linkedin = org.get("linkedin_info") or {}
    industry = linkedin.get("industry") or {}
    keywords = [k.get("name") for k in org.get("keywords") or [] if k.get("name")][:MAX_KEYWORDS]
    founded = org.get("founded_date") or ""

    properties = {
        "name": org.get("name"),
        "domain": normalize_domain(org.get("domain")),
        "website": org.get("website"),
        "description": org.get("description"),
        "annualrevenue": finance.get("revenue"),
        "numberofemployees": org.get("employees_amount"),
        "founded_year": founded[:4] if founded[:4].isdigit() else None,
        "linkedin_company_page": linkedin.get("public_profile_url"),
        **_company_address(org),
        "forager_organization_id": org.get("id"),
        "forager_legal_name": org.get("legal_name"),
        "forager_industry": industry.get("name"),
        "forager_employees_range": org.get("employees_range"),
        "forager_operating_status": org.get("operating_status"),
        "forager_keywords": ", ".join(keywords),
        "forager_logo_url": org.get("logo"),
    }
    return _clean(properties)


def _company_address(org: dict) -> dict:
    addresses = [a for a in org.get("addresses") or [] if isinstance(a, dict)]
    if addresses:
        hq = addresses[0]  # ordering is undocumented; first address treated as HQ
        street = " ".join(p for p in (hq.get("street_number"), hq.get("street_name")) if p)
        return {
            "address": street,
            "city": hq.get("city"),
            "state": hq.get("state"),
            "zip": hq.get("postcode"),
            "country": hq.get("country"),
        }
    city, state, country = parse_location(org.get("location"))
    return {"city": city, "state": state, "country": country}


def _clean(properties: dict) -> dict[str, str]:
    """Drop None/empty values and stringify the rest (HubSpot accepts string values)."""
    return {
        key: str(value)
        for key, value in properties.items()
        if value is not None and (not isinstance(value, str) or value.strip())
    }
