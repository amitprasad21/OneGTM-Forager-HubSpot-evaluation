import copy
import json
from pathlib import Path

import pytest

from app.clients.forager import ForagerError
from app.services.company_enrichment import CompanyEnrichmentService
from tests.fakes import FakeForager, FakeHubSpot

ORG = json.loads((Path(__file__).parent / "fixtures" / "forager_organization.json").read_text())["search_results"][0]
NOW_MS = 1_790_000_000_000


@pytest.fixture
def hubspot():
    return FakeHubSpot()


@pytest.fixture
def forager():
    fake = FakeForager()
    fake.organizations = [copy.deepcopy(ORG)]
    return fake


@pytest.fixture
def service(hubspot, forager):
    return CompanyEnrichmentService(hubspot, forager, clock_ms=lambda: NOW_MS)


async def test_enriches_company_by_domain(service, hubspot, forager):
    hubspot.add("companies", "101", name="Acme", domain="acme.ai")

    result = await service.enrich("101")

    assert forager.called("search_organizations") == [{"domains": ["acme.ai"]}]
    props = hubspot.props("companies", "101")
    assert props["description"] == "Acme AI builds test fixtures."
    assert props["annualrevenue"] == "1000000000"
    assert props["numberofemployees"] == "3500"
    assert props["forager_enrichment_status"] == "enriched"
    assert props["forager_enriched_at"] == str(NOW_MS)
    assert result.status == "enriched"
    assert result.domain == "acme.ai"
    assert result.organization["id"] == 501


async def test_existing_name_and_domain_are_not_overwritten(service, hubspot):
    hubspot.add("companies", "101", name="Acme (Test)", domain="acme.ai")

    await service.enrich("101")

    props = hubspot.props("companies", "101")
    assert props["name"] == "Acme (Test)"
    assert props["domain"] == "acme.ai"


async def test_domain_is_derived_from_website_when_missing(service, hubspot, forager):
    hubspot.add("companies", "101", name="Acme", website="https://www.acme.ai/about")

    await service.enrich("101")

    assert forager.called("search_organizations") == [{"domains": ["acme.ai"]}]
    assert hubspot.props("companies", "101")["domain"] == "acme.ai"


async def test_prefers_result_with_matching_domain(service, hubspot, forager):
    other = copy.deepcopy(ORG) | {"id": 9, "domain": "acme-other.com"}
    forager.organizations = [other, copy.deepcopy(ORG)]
    hubspot.add("companies", "101", domain="acme.ai")

    result = await service.enrich("101")

    assert result.organization["id"] == 501


async def test_falls_back_to_name_autocomplete_without_domain(service, hubspot, forager):
    forager.autocomplete = [{"id": "501", "text": "Acme AI - acme.ai"}]
    hubspot.add("companies", "101", name="Acme AI")

    result = await service.enrich("101")

    assert forager.called("autocomplete_organizations") == [{"query": "Acme AI"}]
    assert forager.called("search_organizations") == [{"organization_ids": [501]}]
    assert result.status == "enriched"


async def test_not_found_records_status_without_other_writes(service, hubspot, forager):
    forager.organizations = []
    hubspot.add("companies", "101", name="Nobody", domain="nobody.example")

    result = await service.enrich("101")

    assert result.status == "not_found"
    assert hubspot.updates == [
        (
            "companies",
            "101",
            {
                "forager_enrichment_status": "not_found",
                "forager_enriched_at": str(NOW_MS),
                "forager_enrichment_notes": "Forager has no organization for domain nobody.example",
            },
        )
    ]


async def test_company_without_domain_or_name_is_not_found_without_credit_spend(service, hubspot, forager):
    hubspot.add("companies", "101")

    result = await service.enrich("101")

    assert result.status == "not_found"
    assert forager.calls == []


async def test_partial_when_key_fields_missing(service, hubspot, forager):
    forager.organizations = [copy.deepcopy(ORG) | {"finance_info": {"revenue": None}, "employees_amount": None}]
    hubspot.add("companies", "101", domain="acme.ai")

    result = await service.enrich("101")

    props = hubspot.props("companies", "101")
    assert result.status == "partial"
    assert props["forager_enrichment_status"] == "partial"
    assert props["forager_enrichment_notes"] == "Forager returned no: annual revenue, employee count"
    assert "annualrevenue" not in props


async def test_missing_hubspot_record_returns_missing(service, forager):
    result = await service.enrich("404")

    assert result.status == "missing"
    assert forager.calls == []


async def test_forager_errors_propagate_for_job_retry(service, hubspot, forager):
    forager.error = ForagerError("boom", 500)
    hubspot.add("companies", "101", domain="acme.ai")

    with pytest.raises(ForagerError):
        await service.enrich("101")
