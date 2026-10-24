import copy
import json
from pathlib import Path

import pytest

from app.services.automation import EnrichmentAutomation
from app.services.contact_enrichment import ContactLookupOptions
from app.title_filter import TitleFilter
from tests.fakes import FakeForager, FakeHubSpot
from tests.test_discovery_service import role

FIXTURES = Path(__file__).parent / "fixtures"
ORG = json.loads((FIXTURES / "forager_organization.json").read_text())["search_results"][0]
PERSON = json.loads((FIXTURES / "forager_person.json").read_text())
NOW_MS = 1_790_000_000_000


@pytest.fixture
def hubspot():
    return FakeHubSpot()


@pytest.fixture
def forager():
    fake = FakeForager()
    fake.organizations = [copy.deepcopy(ORG)]
    fake.people = {"jane-doe-test": copy.deepcopy(PERSON)}
    fake.role_results = [role(1, "VP Engineering"), role(2, "Software Engineer"), role(3, "Head of Research")]
    fake.work_emails = {"jane-doe-test": "jane@acme.ai", "p-1": "p1@acme.ai", "p-3": "p3@acme.ai"}
    fake.phones = {9001: "+14155550100", 1: "+14155550101", 3: "+14155550103"}
    return fake


def make_automation(hubspot, forager, max_phone_lookups=None):
    return EnrichmentAutomation(
        hubspot,
        forager,
        title_filter=TitleFilter(include=["VP", "Head"]),
        max_contacts=5,
        contact_options=lambda: ContactLookupOptions(max_phone_lookups=max_phone_lookups),
        clock_ms=lambda: NOW_MS,
    )


async def test_company_with_existing_contacts_enriches_them_without_discovery(hubspot, forager):
    hubspot.add("companies", "101", domain="acme.ai")
    hubspot.add("contacts", "5", hs_linkedin_url="https://www.linkedin.com/in/jane-doe-test/")
    hubspot.associate("101", "5")

    summary = await make_automation(hubspot, forager).company_created("101")

    assert summary["company_status"] == "enriched"
    assert summary["mode"] == "enriched_existing"
    assert summary["contacts"] == [{"id": "5", "status": "enriched", "missing": []}]
    assert forager.called("search_person_roles") == []
    assert hubspot.props("contacts", "5")["email"] == "jane@acme.ai"


async def test_company_without_contacts_discovers_title_filtered_people(hubspot, forager):
    hubspot.add("companies", "101", domain="acme.ai")

    summary = await make_automation(hubspot, forager).company_created("101")

    assert summary["mode"] == "discovered"
    assert [c["status"] for c in summary["contacts"]] == ["enriched", "enriched"]
    titles = sorted(props["jobtitle"] for _, props, _ in hubspot.created)
    assert titles == ["Head of Research", "VP Engineering"]  # "Software Engineer" filtered out


async def test_phone_limit_applies_per_job(hubspot, forager):
    hubspot.add("companies", "101", domain="acme.ai")

    summary = await make_automation(hubspot, forager, max_phone_lookups=1).company_created("101")

    assert len(forager.called("find_phone")) == 1
    assert [c["status"] for c in summary["contacts"]] == ["enriched", "partial"]


async def test_company_not_found_stops_before_contacts(hubspot, forager):
    forager.organizations = []
    hubspot.add("companies", "101", domain="nobody.example")

    summary = await make_automation(hubspot, forager).company_created("101")

    assert summary == {"company_id": "101", "company_status": "not_found", "mode": None, "contacts": []}
    assert forager.called("search_person_roles") == []


async def test_already_processed_company_is_a_no_op(hubspot, forager):
    hubspot.add("companies", "101", domain="acme.ai", forager_enrichment_status="enriched")

    summary = await make_automation(hubspot, forager).company_created("101")

    assert summary["company_status"] == "skipped"
    assert forager.calls == []


async def test_contact_created_enriches_contact(hubspot, forager):
    hubspot.add("contacts", "5", hs_linkedin_url="https://www.linkedin.com/in/jane-doe-test/")

    summary = await make_automation(hubspot, forager).contact_created("5")

    assert summary == {"contact_id": "5", "status": "enriched", "missing": []}


async def test_contact_created_by_discovery_is_skipped(hubspot, forager):
    hubspot.add("companies", "101", domain="acme.ai")
    automation = make_automation(hubspot, forager)
    await automation.company_created("101")
    created_id = next(object_id for (kind, object_id) in hubspot.objects if kind == "contacts")
    calls_before = len(forager.calls)

    summary = await automation.contact_created(created_id)

    assert summary["status"] == "skipped"
    assert len(forager.calls) == calls_before  # no credits spent on the webhook echo


async def test_mark_failed_writes_failed_status(hubspot, forager):
    hubspot.add("contacts", "5")

    await make_automation(hubspot, forager).mark_failed("contact", "5", "Forager POST failed with HTTP 500")

    props = hubspot.props("contacts", "5")
    assert props["forager_enrichment_status"] == "failed"
    assert props["forager_enrichment_notes"] == "Enrichment failed: Forager POST failed with HTTP 500"
