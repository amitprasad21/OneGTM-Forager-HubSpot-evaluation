"""R4/R5: what happens when HubSpot reports a new company or contact."""

from collections.abc import Callable

from app.log import get_logger, log_event
from app.services.common import FAILED, MISSING, NOT_FOUND, SKIPPED, Clock, now_ms, status_properties
from app.services.company_enrichment import CompanyEnrichmentService
from app.services.contact_discovery import ContactDiscoveryService
from app.services.contact_enrichment import ContactEnrichmentService, ContactLookupOptions
from app.title_filter import TitleFilter

log = get_logger(__name__)

OBJECT_TYPES = {"company": "companies", "contact": "contacts"}


class EnrichmentAutomation:
    def __init__(
        self,
        hubspot,
        forager,
        *,
        title_filter: TitleFilter,
        max_contacts: int,
        contact_options: Callable[[], ContactLookupOptions],
        clock_ms: Clock = now_ms,
    ):
        self._hubspot = hubspot
        self._forager = forager
        self._title_filter = title_filter
        self._max_contacts = max_contacts
        self._contact_options = contact_options
        self._clock = clock_ms
        self._companies = CompanyEnrichmentService(hubspot, forager, clock_ms=clock_ms)

    def _contact_service(self) -> ContactEnrichmentService:
        # A fresh service per job, so per-job limits such as phone lookups reset.
        return ContactEnrichmentService(self._hubspot, self._forager, self._contact_options(), clock_ms=self._clock)

    async def company_created(self, company_id: str, *, force: bool = False) -> dict:
        """Enrich the company, then its existing contacts, or discover contacts if it has none."""
        company = await self._companies.enrich(company_id, force=force)
        summary = {"company_id": company_id, "company_status": company.status, "mode": None, "contacts": []}
        if company.status in (MISSING, NOT_FOUND, SKIPPED):
            return summary

        contacts = self._contact_service()
        contact_ids = await self._hubspot.list_associated_ids("companies", company_id, "contacts")
        if contact_ids:
            summary["mode"] = "enriched_existing"
            results = [await contacts.enrich(contact_id) for contact_id in contact_ids]
        elif company.domain:
            summary["mode"] = "discovered"
            discovery = ContactDiscoveryService(self._hubspot, self._forager, contacts, clock_ms=self._clock)
            results = await discovery.discover_and_create(
                company_id, company.domain, self._title_filter, self._max_contacts
            )
        else:
            results = []

        summary["contacts"] = [{"id": r.object_id, "status": r.status, "missing": r.missing} for r in results]
        log_event(log, "automation.company_done", company_id=company_id, mode=summary["mode"], contacts=len(results))
        return summary

    async def contact_created(self, contact_id: str, *, force: bool = False) -> dict:
        result = await self._contact_service().enrich(contact_id, force=force)
        return {"contact_id": contact_id, "status": result.status, "missing": result.missing}

    async def mark_failed(self, object_type: str, object_id: str, error: str) -> None:
        await self._hubspot.update_object(
            OBJECT_TYPES[object_type],
            object_id,
            status_properties(FAILED, self._clock, f"Enrichment failed: {error}"[:1000]),
        )
