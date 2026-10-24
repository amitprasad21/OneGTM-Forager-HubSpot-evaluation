"""R2: enrich a HubSpot contact with Forager person, email and phone data."""

from dataclasses import dataclass, field

from app.credits import CreditBudgetExceeded
from app.log import get_logger, log_event
from app.mapping import linkedin_slug, map_contact, normalize_domain, person_from_role_result
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

READ_PROPERTIES = [
    "firstname", "lastname", "email", "phone", "hs_linkedin_url", "company",
    "forager_person_id", STATUS_PROPERTY,
]
FILL_ONLY_PROPERTIES = ("firstname", "lastname")
REQUIRED_FIELDS = {
    "firstname": "first name",
    "lastname": "last name",
    "hs_linkedin_url": "LinkedIn URL",
    "jobtitle": "job title",
    "company": "company name",
    "forager_company_domain": "company domain",
    "forager_company_linkedin_url": "company LinkedIn URL",
    "email": "email",
    "phone": "phone",
    "city": "city",
    "state": "state",
    "country": "country",
}
WEBMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com",
    "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com",
}


@dataclass
class ContactLookupOptions:
    enable_phone: bool = True
    enable_personal_email: bool = True
    include_extra_fields: bool = False
    max_phone_lookups: int | None = None  # per service instance; None = only the credit budget applies


@dataclass
class ContactData:
    properties: dict[str, str]
    missing: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return PARTIAL if self.missing else ENRICHED

    @property
    def notes(self) -> str:
        if not self.missing:
            return ""
        reasons = f" ({'; '.join(self.reasons)})" if self.reasons else ""
        return f"Missing from Forager: {', '.join(self.missing)}{reasons}"


class ContactEnrichmentService:
    def __init__(self, hubspot, forager, options: ContactLookupOptions | None = None, clock_ms: Clock = now_ms):
        self._hubspot = hubspot
        self._forager = forager
        self._options = options or ContactLookupOptions()
        self._clock = clock_ms
        self._phone_lookups = 0

    async def enrich(self, contact_id: str, *, force: bool = False) -> EnrichmentResult:
        contact = await self._hubspot.get_object("contacts", contact_id, READ_PROPERTIES)
        if contact is None:
            return EnrichmentResult(contact_id, MISSING)
        current = {k: v for k, v in (contact.get("properties") or {}).items() if v}

        # Loop/double-spend guard: contacts we created or already enriched emit
        # contact.creation too; only failed ones are retried automatically.
        existing_status = current.get(STATUS_PROPERTY)
        if existing_status and existing_status != FAILED and not force:
            log_event(log, "contact.skipped", contact_id=contact_id, status=existing_status)
            return EnrichmentResult(contact_id, SKIPPED)

        domain = await self._company_domain(contact_id, current)
        person, tried = await self._identify(current, domain)
        if person is None:
            notes = (
                "Forager has no matching person"
                if tried
                else "Not enough data to identify this person in Forager "
                "(need LinkedIn URL, name + company domain, or email)"
            )
            await self._hubspot.update_object("contacts", contact_id, status_properties(NOT_FOUND, self._clock, notes))
            log_event(log, "contact.not_found", contact_id=contact_id, tried=tried)
            return EnrichmentResult(contact_id, NOT_FOUND, domain=domain)

        data = await self.build_properties(person, current=current, prefer_domain=domain)
        properties = dict(data.properties)
        for key in FILL_ONLY_PROPERTIES:
            if current.get(key):
                properties.pop(key, None)
        properties.update(status_properties(data.status, self._clock, data.notes))
        await self._hubspot.update_object("contacts", contact_id, properties)

        log_event(log, "contact.enriched", contact_id=contact_id, status=data.status, missing=data.missing)
        return EnrichmentResult(contact_id, data.status, missing=data.missing, domain=domain, person=person)

    async def build_properties(
        self, person: dict, *, current: dict | None = None, prefer_domain: str | None = None
    ) -> ContactData:
        """Map a Forager person and look up email/phone for fields not already set."""
        current = current or {}
        properties = map_contact(
            person, prefer_domain=prefer_domain, include_extra_fields=self._options.include_extra_fields
        )
        reasons: list[str] = []

        if not current.get("email"):
            email = await self._lookup_email(person, properties, reasons)
            if email:
                properties["email"] = email

        if not current.get("phone"):
            phone = await self._lookup_phone(person, reasons)
            if phone:
                properties["phone"] = phone

        present = {**current, **properties}
        missing = [label for key, label in REQUIRED_FIELDS.items() if not present.get(key)]
        return ContactData(properties, missing, list(dict.fromkeys(reasons)))

    # --- identification --------------------------------------------------------

    async def _company_domain(self, contact_id: str, current: dict) -> str | None:
        for company_id in await self._hubspot.list_associated_ids("contacts", contact_id, "companies"):
            company = await self._hubspot.get_object("companies", company_id, ["domain", "website"])
            props = (company or {}).get("properties") or {}
            domain = normalize_domain(props.get("domain")) or normalize_domain(props.get("website"))
            if domain:
                return domain
        email_domain = normalize_domain((current.get("email") or "").rpartition("@")[2])
        return email_domain if email_domain and email_domain not in WEBMAIL_DOMAINS else None

    async def _identify(self, current: dict, domain: str | None) -> tuple[dict | None, list[str]]:
        """Find the person, cheapest method first. Returns (person, methods tried)."""
        tried: list[str] = []

        person_id = current.get("forager_person_id")
        if person_id and str(person_id).isdigit():
            tried.append("forager_person_id")
            person = await self._forager.get_person_detail(person_id=int(person_id))
            if person:
                return person, tried

        slug = linkedin_slug(current.get("hs_linkedin_url"))
        if slug:
            tried.append("linkedin")
            person = await self._forager.get_person_detail(linkedin_slug=slug)
            if person:
                return person, tried

        first, last = current.get("firstname"), current.get("lastname")
        if first and last and domain:
            tried.append("name_domain")
            name = f"{first} {last}".replace('"', "")
            results = (
                await self._forager.search_person_roles(
                    person_name=f'"{name}"', organization_domains=[domain], role_is_current=True
                )
            ).get("search_results") or []
            if results:
                return person_from_role_result(results[0]), tried

        if current.get("email"):
            tried.append("email")
            person = await self._forager.reverse_lookup_email(current["email"])
            if person:
                return person, tried

        return None, tried

    # --- contact data ----------------------------------------------------------

    async def _lookup_email(self, person: dict, properties: dict, reasons: list[str]) -> str | None:
        slug = linkedin_slug(properties.get("hs_linkedin_url"))
        try:
            if slug:
                email = await self._forager.find_work_email(linkedin_slug=slug)
            elif properties.get("firstname") and properties.get("lastname") and properties.get("forager_company_domain"):
                email = await self._forager.find_work_email(
                    first_name=properties["firstname"],
                    last_name=properties["lastname"],
                    domain=properties["forager_company_domain"],
                )
            else:
                email = None
            if not email and self._options.enable_personal_email and person.get("id"):
                email = await self._forager.find_personal_email(person_id=person["id"])
            return email
        except CreditBudgetExceeded:
            reasons.append("credit budget reached")
            return None

    async def _lookup_phone(self, person: dict, reasons: list[str]) -> str | None:
        if not self._options.enable_phone:
            reasons.append("phone lookup disabled")
            return None
        limit = self._options.max_phone_lookups
        if limit is not None and self._phone_lookups >= limit:
            reasons.append("phone lookup limit reached")
            return None
        if not person.get("id"):
            return None
        try:
            self._phone_lookups += 1
            return await self._forager.find_phone(person_id=person["id"])
        except CreditBudgetExceeded:
            reasons.append("credit budget reached")
            return None
