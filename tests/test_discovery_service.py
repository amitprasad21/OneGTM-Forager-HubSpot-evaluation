import copy
import json
from pathlib import Path

import pytest

from app.clients.hubspot import HubSpotError
from app.services.contact_discovery import ContactDiscoveryService
from app.services.contact_enrichment import ContactEnrichmentService, ContactLookupOptions
from app.title_filter import TitleFilter
from tests.fakes import FakeForager, FakeHubSpot

ROLE_RESULT = json.loads(
    (Path(__file__).parent / "fixtures" / "forager_role_search.json").read_text()
)["search_results"][0]
NOW_MS = 1_790_000_000_000


def role(person_id, title, *, current=True, domain="acme.ai", first="P", last=None):
    result = copy.deepcopy(ROLE_RESULT)
    result["role_title"] = title
    result["is_current"] = current
    result["organization"]["domain"] = domain
    result["person"].update(
        id=person_id,
        first_name=first,
        last_name=last or str(person_id),
        full_name=f"{first} {last or person_id}",
        linkedin_info={
            "public_identifier": f"p-{person_id}",
            "public_profile_url": f"https://www.linkedin.com/in/p-{person_id}/",
        },
    )
    return result


@pytest.fixture
def hubspot():
    hubspot = FakeHubSpot()
    hubspot.add("companies", "101", domain="acme.ai")
    return hubspot


@pytest.fixture
def forager():
    fake = FakeForager()
    fake.role_results = [
        role(1, "VP Engineering"),
        role(2, "Software Engineer"),
        role(3, "Head of Sales"),
        role(4, "Executive Assistant to the VP"),
        role(5, "VP Marketing", current=False),
        role(6, "VP Finance", domain="other.example"),
        role(7, "Director of Product"),
    ]
    fake.work_emails = {f"p-{i}": f"p{i}@acme.ai" for i in range(1, 10)}
    fake.phones = {1: "+14155550101", 3: "+14155550103"}
    return fake


def make_service(hubspot, forager, **options):
    contacts = ContactEnrichmentService(
        hubspot, forager, ContactLookupOptions(**options), clock_ms=lambda: NOW_MS
    )
    return ContactDiscoveryService(hubspot, forager, contacts, clock_ms=lambda: NOW_MS)


VP_HEAD = TitleFilter(include=["VP", "Head"], exclude=["Assistant"])


async def test_find_candidates_applies_title_filter_and_current_employer(hubspot, forager):
    service = make_service(hubspot, forager)

    candidates = await service.find_candidates("acme.ai", VP_HEAD, limit=10)

    assert [c["id"] for c in candidates] == [1, 3]
    assert forager.called("search_person_roles") == [
        {"page": 1, "organization_domains": ["acme.ai"], "role_is_current": True, "role_title": '"VP" OR "Head"'}
    ]


async def test_different_filters_surface_different_people(hubspot, forager):
    service = make_service(hubspot, forager)

    engineers = await service.find_candidates("acme.ai", TitleFilter(include=["Engineer"]), limit=10)
    directors = await service.find_candidates("acme.ai", TitleFilter(include=["Director"]), limit=10)

    assert [c["id"] for c in engineers] == [2]
    assert [c["id"] for c in directors] == [7]


async def test_find_candidates_respects_limit_and_dedupes_people(hubspot, forager):
    forager.role_results = [role(1, "VP A"), role(1, "VP B"), role(3, "VP C"), role(8, "VP D")]
    service = make_service(hubspot, forager)

    candidates = await service.find_candidates("acme.ai", VP_HEAD, limit=2)

    assert [c["id"] for c in candidates] == [1, 3]


async def test_fetches_next_page_only_when_allowed_and_needed(hubspot, forager):
    forager.role_results = [role(1, "VP A")]
    service = make_service(hubspot, forager)
    service.max_pages = 2

    original = forager.search_person_roles

    async def paged(page=1, **filters):
        response = await original(page=page, **filters)
        return response | {"total_search_results": 2} if page == 1 else {"search_results": [role(9, "VP Z")], "total_search_results": 2}

    forager.search_person_roles = paged

    candidates = await service.find_candidates("acme.ai", VP_HEAD, limit=5)

    assert [c["id"] for c in candidates] == [1, 9]


async def test_discover_and_create_creates_enriched_associated_contacts(hubspot, forager):
    service = make_service(hubspot, forager)

    results = await service.discover_and_create("101", "acme.ai", VP_HEAD, limit=5)

    assert [r.status for r in results] == ["enriched", "enriched"]
    assert len(hubspot.created) == 2
    object_type, props, associate_with = hubspot.created[0]
    assert object_type == "contacts"
    assert associate_with == ("companies", "101")
    assert props["jobtitle"] == "VP Engineering"
    assert props["email"] == "p1@acme.ai"
    assert props["phone"] == "+14155550101"
    assert props["forager_enrichment_status"] == "enriched"  # contact.creation webhook will skip it
    assert sorted(await hubspot.list_associated_ids("companies", "101", "contacts")) == sorted(r.object_id for r in results)


async def test_existing_hubspot_contacts_are_not_duplicated(hubspot, forager):
    hubspot.add("contacts", "50", forager_person_id="1")
    hubspot.add("contacts", "51", hs_linkedin_url="https://www.linkedin.com/in/p-3/")
    service = make_service(hubspot, forager)

    results = await service.discover_and_create("101", "acme.ai", VP_HEAD, limit=5)

    assert results == []
    assert hubspot.created == []
    assert forager.called("find_phone") == []  # no credits spent on known people


async def test_duplicate_email_conflict_is_skipped_not_fatal(hubspot, forager):
    service = make_service(hubspot, forager)
    calls = {"n": 0}
    original = hubspot.create_object

    async def conflict_once(object_type, properties, *, associate_with=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise HubSpotError("conflict", 409, "CONFLICT")
        return await original(object_type, properties, associate_with=associate_with)

    hubspot.create_object = conflict_once

    results = await service.discover_and_create("101", "acme.ai", VP_HEAD, limit=5)

    assert [r.status for r in results] == ["skipped", "enriched"]


async def test_partial_contacts_are_created_with_honest_status(hubspot, forager):
    forager.phones = {}
    service = make_service(hubspot, forager)

    results = await service.discover_and_create("101", "acme.ai", TitleFilter(include=["VP Engineering"]), limit=1)

    _, props, _ = hubspot.created[0]
    assert results[0].status == "partial"
    assert props["forager_enrichment_status"] == "partial"
    assert props["forager_enrichment_notes"].startswith("Missing from Forager: phone")
    assert "phone" not in props
