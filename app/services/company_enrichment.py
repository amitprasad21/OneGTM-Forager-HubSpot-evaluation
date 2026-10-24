"""R1: enrich a HubSpot company with Forager organization data."""

from app.log import get_logger, log_event
from app.mapping import map_company, normalize_domain
from app.services.common import (
    ENRICHED,
    FAILED,
    MISSING,
    NOT_FOUND,
    PARTIAL,
    SKIPPED,
    STATUS_PROPERTY,
    Clock,
    EnrichmentResult,
    now_ms,
    status_properties,
)

log = get_logger(__name__)

READ_PROPERTIES = ["name", "domain", "website", STATUS_PROPERTY]
FILL_ONLY_PROPERTIES = ("name", "domain")  # never overwrite what a user typed
KEY_FIELDS = {
    "description": "description",
    "annualrevenue": "annual revenue",
    "numberofemployees": "employee count",
    "linkedin_company_page": "LinkedIn page",
    "country": "location",
}


class CompanyEnrichmentService:
    def __init__(self, hubspot, forager, clock_ms: Clock = now_ms):
        self._hubspot = hubspot
        self._forager = forager
        self._clock = clock_ms

    async def enrich(self, company_id: str, *, force: bool = False) -> EnrichmentResult:
        company = await self._hubspot.get_object("companies", company_id, READ_PROPERTIES)
        if company is None:
            log_event(log, "company.missing", company_id=company_id)
            return EnrichmentResult(company_id, MISSING)

        current = company.get("properties") or {}
        domain = normalize_domain(current.get("domain")) or normalize_domain(current.get("website"))
        name = (current.get("name") or "").strip()

        # Durable idempotency guard: replays and re-queued jobs spend no credits.
        existing_status = current.get(STATUS_PROPERTY)
        if existing_status and existing_status != FAILED and not force:
            log_event(log, "company.skipped", company_id=company_id, status=existing_status)
            return EnrichmentResult(company_id, SKIPPED, domain=domain)

        organization = await self._find_organization(domain, name)
        if organization is None:
            target = f"domain {domain}" if domain else f"name {name!r}" if name else "a company without domain or name"
            await self._hubspot.update_object(
                "companies",
                company_id,
                status_properties(NOT_FOUND, self._clock, f"Forager has no organization for {target}"),
            )
            log_event(log, "company.not_found", company_id=company_id)
            return EnrichmentResult(company_id, NOT_FOUND, domain=domain)

        properties = map_company(organization)
        for key in FILL_ONLY_PROPERTIES:
            if current.get(key):
                properties.pop(key, None)

        missing = [label for key, label in KEY_FIELDS.items() if key not in properties]
        status = PARTIAL if missing else ENRICHED
        notes = f"Forager returned no: {', '.join(missing)}" if missing else ""
        properties.update(status_properties(status, self._clock, notes))
        await self._hubspot.update_object("companies", company_id, properties)

        log_event(log, "company.enriched", company_id=company_id, status=status, missing=missing)
        return EnrichmentResult(
            company_id,
            status,
            missing=missing,
            domain=domain or normalize_domain(organization.get("domain")),
            organization=organization,
        )

    async def _find_organization(self, domain: str | None, name: str) -> dict | None:
        if domain:
            results = (await self._forager.search_organizations(domains=[domain])).get("search_results") or []
            matching = [r for r in results if normalize_domain(r.get("domain")) == domain]
            return (matching or results or [None])[0]

        if name:
            suggestions = await self._forager.autocomplete_organizations(name)
            ids = [int(s["id"]) for s in suggestions if str(s.get("id", "")).isdigit()]
            if ids:
                results = (await self._forager.search_organizations(organization_ids=ids[:1])).get("search_results") or []
                return results[0] if results else None
        return None
