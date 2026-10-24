"""R3: discover contacts at a company with job-title filtering, then create them in HubSpot."""

from app.clients.hubspot import HubSpotError
from app.log import get_logger, log_event
from app.mapping import normalize_domain, person_from_role_result
from app.services.common import SKIPPED, Clock, EnrichmentResult, now_ms, status_properties
from app.title_filter import TitleFilter

log = get_logger(__name__)


class ContactDiscoveryService:
    def __init__(self, hubspot, forager, contact_service, clock_ms: Clock = now_ms, max_pages: int = 1):
        self._hubspot = hubspot
        self._forager = forager
        self._contacts = contact_service
        self._clock = clock_ms
        self.max_pages = max_pages  # each page costs 1 credit

    async def find_candidates(
        self, domain: str, title_filter: TitleFilter, limit: int | None = None
    ) -> list[dict]:
        """Current employees at `domain` whose title passes the filter (person-detail shaped)."""
        candidates: list[dict] = []
        seen: set = set()
        filters = {"organization_domains": [domain], "role_is_current": True}
        if query := title_filter.forager_query():
            filters["role_title"] = query

        fetched = 0
        for page in range(1, self.max_pages + 1):
            response = await self._forager.search_person_roles(page=page, **filters)
            results = response.get("search_results") or []
            fetched += len(results)
            for result in results:
                person_id = (result.get("person") or {}).get("id")
                org_domain = normalize_domain((result.get("organization") or {}).get("domain"))
                if (
                    person_id is None
                    or person_id in seen
                    or not result.get("is_current")
                    or org_domain != domain
                    or not title_filter.matches(result.get("role_title"))
                ):
                    continue
                seen.add(person_id)
                candidates.append(person_from_role_result(result))
                if limit is not None and len(candidates) >= limit:
                    return candidates
            if not results or fetched >= (response.get("total_search_results") or 0):
                break

        log_event(log, "discovery.candidates", domain=domain, found=len(candidates), filter=title_filter.describe())
        return candidates

    async def discover_and_create(
        self, company_id: str, domain: str, title_filter: TitleFilter, limit: int
    ) -> list[EnrichmentResult]:
        """Find, enrich and create up to `limit` new contacts associated with the company."""
        results: list[EnrichmentResult] = []
        for person in await self.find_candidates(domain, title_filter):
            if len(results) >= limit:
                break
            if await self._already_in_hubspot(person):
                log_event(log, "discovery.duplicate_skipped", company_id=company_id, person_id=person.get("id"))
                continue

            data = await self._contacts.build_properties(person, prefer_domain=domain)
            # Written with its final status so the resulting contact.creation webhook is a no-op.
            properties = {**data.properties, **status_properties(data.status, self._clock, data.notes)}
            try:
                created = await self._hubspot.create_object(
                    "contacts", properties, associate_with=("companies", company_id)
                )
            except HubSpotError as error:
                if error.status_code != 409:
                    raise
                log_event(log, "discovery.create_conflict", company_id=company_id, person_id=person.get("id"))
                results.append(EnrichmentResult("", SKIPPED, person=person))
                continue

            results.append(
                EnrichmentResult(created["id"], data.status, missing=data.missing, domain=domain, person=person)
            )
            log_event(log, "discovery.contact_created", company_id=company_id, contact_id=created["id"], status=data.status)
        return results

    async def _already_in_hubspot(self, person: dict) -> bool:
        checks = [
            ("forager_person_id", str(person["id"]) if person.get("id") is not None else None),
            ("hs_linkedin_url", (person.get("linkedin_info") or {}).get("public_profile_url")),
        ]
        for property_name, value in checks:
            if value and await self._hubspot.find_by_property("contacts", property_name, value, ["email"]):
                return True
        return False
