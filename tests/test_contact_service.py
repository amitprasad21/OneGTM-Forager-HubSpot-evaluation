import copy
import json
from pathlib import Path

import pytest

from app.services.contact_enrichment import ContactEnrichmentService, ContactLookupOptions
from tests.fakes import FakeForager, FakeHubSpot

FIXTURES = Path(__file__).parent / "fixtures"
PERSON = json.loads((FIXTURES / "forager_person.json").read_text())
ROLE_RESULT = json.loads((FIXTURES / "forager_role_search.json").read_text())["search_results"][0]
NOW_MS = 1_790_000_000_000
LINKEDIN = "https://www.linkedin.com/in/jane-doe-test/"


@pytest.fixture
def hubspot():
    return FakeHubSpot()


@pytest.fixture
def forager():
    fake = FakeForager()
    fake.people = {9001: copy.deepcopy(PERSON), "jane-doe-test": copy.deepcopy(PERSON)}
    fake.work_emails = {"jane-doe-test": "jane@acme.ai"}
    fake.phones = {9001: "+14155550100"}
    return fake


def make_service(hubspot, forager, **options):
    return ContactEnrichmentService(hubspot, forager, ContactLookupOptions(**options), clock_ms=lambda: NOW_MS)


@pytest.fixture
def service(hubspot, forager):
    return make_service(hubspot, forager)


async def test_enriches_contact_identified_by_linkedin_url(service, hubspot, forager):
    hubspot.add("contacts", "5", hs_linkedin_url=LINKEDIN)

    result = await service.enrich("5")

    assert forager.called("get_person_detail") == [{"person_id": None, "linkedin_slug": "jane-doe-test"}]
    props = hubspot.props("contacts", "5")
    assert props["firstname"] == "Jane"
    assert props["lastname"] == "Doe"
    assert props["jobtitle"] == "VP Engineering"
    assert props["company"] == "Acme AI"
    assert props["forager_company_domain"] == "acme.ai"
    assert props["email"] == "jane@acme.ai"
    assert props["phone"] == "+14155550100"
    assert (props["city"], props["state"], props["country"]) == ("San Francisco", "California", "United States")
    assert props["forager_enrichment_status"] == "enriched"
    assert props["forager_enrichment_notes"] == ""
    assert result.status == "enriched"


async def test_known_forager_person_id_is_used_first(service, hubspot, forager):
    hubspot.add("contacts", "5", forager_person_id="9001", hs_linkedin_url=LINKEDIN)

    await service.enrich("5")

    assert forager.called("get_person_detail") == [{"person_id": 9001, "linkedin_slug": None}]


async def test_name_and_associated_company_domain_use_role_search(service, hubspot, forager):
    forager.role_results = [copy.deepcopy(ROLE_RESULT)]
    hubspot.add("companies", "101", domain="acme.ai")
    hubspot.add("contacts", "5", firstname="Jane", lastname="Doe")
    hubspot.associate("101", "5")

    result = await service.enrich("5")

    assert forager.called("search_person_roles") == [
        {"page": 1, "person_name": '"Jane Doe"', "organization_domains": ["acme.ai"], "role_is_current": True}
    ]
    assert forager.called("get_person_detail") == []  # search result is enough; saves a credit
    assert hubspot.props("contacts", "5")["jobtitle"] == "VP Engineering"
    assert result.status == "enriched"


async def test_work_email_domain_is_used_when_no_company_is_associated(service, hubspot, forager):
    forager.role_results = [copy.deepcopy(ROLE_RESULT)]
    hubspot.add("contacts", "5", firstname="Jane", lastname="Doe", email="jane@acme.ai")

    await service.enrich("5")

    assert forager.called("search_person_roles")[0]["organization_domains"] == ["acme.ai"]
    assert forager.called("reverse_lookup_email") == []


async def test_reverse_email_lookup_is_last_resort(service, hubspot, forager):
    forager.people_by_email = {"jane@gmail.com": copy.deepcopy(PERSON)}
    hubspot.add("contacts", "5", email="jane@gmail.com")

    result = await service.enrich("5")

    assert forager.called("search_person_roles") == []  # webmail domain is not an employer
    assert forager.called("reverse_lookup_email") == [{"email": "jane@gmail.com"}]
    assert result.status == "enriched"


async def test_existing_email_and_names_are_kept_and_email_lookup_skipped(service, hubspot, forager):
    hubspot.add("contacts", "5", hs_linkedin_url=LINKEDIN, email="typed@acme.ai", firstname="Janie")

    await service.enrich("5")

    props = hubspot.props("contacts", "5")
    assert props["email"] == "typed@acme.ai"
    assert props["firstname"] == "Janie"
    assert forager.called("find_work_email") == []


async def test_personal_email_fallback_when_no_work_email(service, hubspot, forager):
    forager.work_emails = {}
    forager.personal_emails = {9001: "jane.personal@gmail.com"}
    hubspot.add("contacts", "5", hs_linkedin_url=LINKEDIN)

    await service.enrich("5")

    assert hubspot.props("contacts", "5")["email"] == "jane.personal@gmail.com"


async def test_personal_email_fallback_can_be_disabled(hubspot, forager):
    forager.work_emails = {}
    forager.personal_emails = {9001: "jane.personal@gmail.com"}
    hubspot.add("contacts", "5", hs_linkedin_url=LINKEDIN)

    await make_service(hubspot, forager, enable_personal_email=False).enrich("5")

    assert forager.called("find_personal_email") == []
    assert "email" not in hubspot.props("contacts", "5")


async def test_unavailable_email_and_phone_give_partial_with_notes(service, hubspot, forager):
    forager.work_emails = {}
    forager.phones = {}
    hubspot.add("contacts", "5", hs_linkedin_url=LINKEDIN)

    result = await service.enrich("5")

    props = hubspot.props("contacts", "5")
    assert result.status == "partial"
    assert result.missing == ["email", "phone"]
    assert props["forager_enrichment_status"] == "partial"
    assert props["forager_enrichment_notes"] == "Missing from Forager: email, phone"
    assert "email" not in props and "phone" not in props


async def test_phone_quota_limits_phone_lookups(hubspot, forager):
    service = make_service(hubspot, forager, max_phone_lookups=1)
    hubspot.add("contacts", "5", hs_linkedin_url=LINKEDIN)
    hubspot.add("contacts", "6", forager_person_id="9001")

    await service.enrich("5")
    second = await service.enrich("6")

    assert len(forager.called("find_phone")) == 1
    assert second.status == "partial"
    assert hubspot.props("contacts", "6")["forager_enrichment_notes"] == (
        "Missing from Forager: phone (phone lookup limit reached)"
    )


async def test_phone_lookup_can_be_disabled(hubspot, forager):
    hubspot.add("contacts", "5", hs_linkedin_url=LINKEDIN)

    await make_service(hubspot, forager, enable_phone=False).enrich("5")

    assert forager.called("find_phone") == []
    assert "(phone lookup disabled)" in hubspot.props("contacts", "5")["forager_enrichment_notes"]


async def test_credit_budget_exhaustion_degrades_to_partial(hubspot, forager):
    forager.ledger.budget = 3  # enough for the detail lookup, not for email (5) or phone (15)
    forager.work_emails = {}
    hubspot.add("contacts", "5", hs_linkedin_url=LINKEDIN)

    result = await make_service(hubspot, forager).enrich("5")

    assert result.status == "partial"
    assert "credit budget reached" in hubspot.props("contacts", "5")["forager_enrichment_notes"]


async def test_already_enriched_contact_is_skipped_without_forager_calls(service, hubspot, forager):
    hubspot.add("contacts", "5", hs_linkedin_url=LINKEDIN, forager_enrichment_status="enriched")

    result = await service.enrich("5")

    assert result.status == "skipped"
    assert forager.calls == []
    assert hubspot.updates == []


async def test_partial_contact_is_also_skipped_unless_forced(service, hubspot, forager):
    hubspot.add("contacts", "5", hs_linkedin_url=LINKEDIN, forager_enrichment_status="partial")

    assert (await service.enrich("5")).status == "skipped"
    assert (await service.enrich("5", force=True)).status == "enriched"


async def test_failed_contact_is_retried(service, hubspot):
    hubspot.add("contacts", "5", hs_linkedin_url=LINKEDIN, forager_enrichment_status="failed")

    assert (await service.enrich("5")).status == "enriched"


async def test_unidentifiable_contact_is_not_found(service, hubspot, forager):
    hubspot.add("contacts", "5", firstname="Only")

    result = await service.enrich("5")

    assert result.status == "not_found"
    assert forager.calls == []
    assert hubspot.props("contacts", "5")["forager_enrichment_notes"] == (
        "Not enough data to identify this person in Forager (need LinkedIn URL, name + company domain, or email)"
    )


async def test_person_not_in_forager_is_not_found(service, hubspot, forager):
    forager.people = {}
    hubspot.add("contacts", "5", hs_linkedin_url="https://www.linkedin.com/in/nobody/")

    result = await service.enrich("5")

    assert result.status == "not_found"
    assert hubspot.props("contacts", "5")["forager_enrichment_notes"] == "Forager has no matching person"


async def test_missing_hubspot_contact(service, forager):
    assert (await service.enrich("404")).status == "missing"
    assert forager.calls == []


async def test_build_properties_for_new_contact_includes_lookups(service):
    data = await service.build_properties(copy.deepcopy(PERSON), prefer_domain="acme.ai")

    assert data.properties["email"] == "jane@acme.ai"
    assert data.properties["phone"] == "+14155550100"
    assert data.missing == []
