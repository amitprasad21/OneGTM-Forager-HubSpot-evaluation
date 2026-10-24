import json

import httpx
import pytest
import respx

from app.clients.hubspot import HubSpotClient, HubSpotError

BASE = "https://api.hubapi.com"


async def no_sleep(_seconds):
    return None


@pytest.fixture
async def hubspot():
    client = HubSpotClient(access_token="pat-test-token", sleep=no_sleep)
    yield client
    await client.aclose()


def body(route):
    return json.loads(route.calls.last.request.content)


@respx.mock
async def test_get_object_sends_bearer_and_properties(hubspot):
    route = respx.get(f"{BASE}/crm/v3/objects/companies/101").mock(
        return_value=httpx.Response(200, json={"id": "101", "properties": {"domain": "openai.com"}})
    )

    company = await hubspot.get_object("companies", "101", ["domain", "name"])

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer pat-test-token"
    assert request.url.params["properties"] == "domain,name"
    assert company["properties"]["domain"] == "openai.com"


@respx.mock
async def test_get_object_returns_none_on_404(hubspot):
    respx.get(f"{BASE}/crm/v3/objects/contacts/9").mock(return_value=httpx.Response(404))

    assert await hubspot.get_object("contacts", "9", ["email"]) is None


@respx.mock
async def test_update_object_patches_properties(hubspot):
    route = respx.patch(f"{BASE}/crm/v3/objects/contacts/5").mock(
        return_value=httpx.Response(200, json={"id": "5", "properties": {}})
    )

    await hubspot.update_object("contacts", "5", {"jobtitle": "CTO"})

    assert body(route) == {"properties": {"jobtitle": "CTO"}}


@respx.mock
async def test_create_object_with_default_company_association(hubspot):
    route = respx.post(f"{BASE}/crm/v3/objects/contacts").mock(
        return_value=httpx.Response(201, json={"id": "77", "properties": {}})
    )

    created = await hubspot.create_object(
        "contacts", {"firstname": "Jane"}, associate_with=("companies", "101")
    )

    assert created["id"] == "77"
    assert body(route) == {
        "properties": {"firstname": "Jane"},
        "associations": [
            {
                "to": {"id": "101"},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 1}],
            }
        ],
    }


@respx.mock
async def test_find_by_property_uses_search_eq_filter(hubspot):
    route = respx.post(f"{BASE}/crm/v3/objects/contacts/search").mock(
        return_value=httpx.Response(200, json={"total": 1, "results": [{"id": "5", "properties": {}}]})
    )

    found = await hubspot.find_by_property("contacts", "hs_linkedin_url", "https://x", ["email"])

    assert found["id"] == "5"
    assert body(route) == {
        "filterGroups": [{"filters": [{"propertyName": "hs_linkedin_url", "operator": "EQ", "value": "https://x"}]}],
        "properties": ["email"],
        "limit": 1,
    }


@respx.mock
async def test_find_by_property_returns_none_when_no_results(hubspot):
    respx.post(f"{BASE}/crm/v3/objects/contacts/search").mock(
        return_value=httpx.Response(200, json={"total": 0, "results": []})
    )

    assert await hubspot.find_by_property("contacts", "email", "a@b.co", []) is None


@respx.mock
async def test_list_associated_ids_follows_pagination(hubspot):
    url = f"{BASE}/crm/v4/objects/companies/101/associations/contacts"
    route = respx.get(url).mock(
        side_effect=[
            httpx.Response(200, json={"results": [{"toObjectId": 1}, {"toObjectId": 2}], "paging": {"next": {"after": "abc"}}}),
            httpx.Response(200, json={"results": [{"toObjectId": 3}]}),
        ]
    )

    ids = await hubspot.list_associated_ids("companies", "101", "contacts")

    assert ids == ["1", "2", "3"]
    assert route.calls[1].request.url.params["after"] == "abc"


@respx.mock
async def test_associate_default_puts_v4_default_association(hubspot):
    route = respx.put(f"{BASE}/crm/v4/objects/contacts/77/associations/default/companies/101").mock(
        return_value=httpx.Response(200, json={"status": "COMPLETE"})
    )

    await hubspot.associate_default("contacts", "77", "companies", "101")

    assert route.called


@respx.mock
async def test_errors_raise_with_status_and_category(hubspot):
    respx.patch(f"{BASE}/crm/v3/objects/contacts/5").mock(
        return_value=httpx.Response(
            400, json={"status": "error", "category": "VALIDATION_ERROR", "message": "Property values were not valid"}
        )
    )

    with pytest.raises(HubSpotError) as excinfo:
        await hubspot.update_object("contacts", "5", {"bogus": "x"})

    assert excinfo.value.status_code == 400
    assert excinfo.value.category == "VALIDATION_ERROR"
    assert "pat-test-token" not in str(excinfo.value)


@respx.mock
async def test_rate_limit_is_retried(hubspot):
    route = respx.get(f"{BASE}/crm/v3/objects/companies/1").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200, json={"id": "1"})]
    )

    assert (await hubspot.get_object("companies", "1", []))["id"] == "1"
    assert route.call_count == 2


@respx.mock
async def test_get_property_names(hubspot):
    respx.get(f"{BASE}/crm/v3/properties/contacts").mock(
        return_value=httpx.Response(200, json={"results": [{"name": "email"}, {"name": "forager_person_id"}]})
    )

    assert await hubspot.get_property_names("contacts") == {"email", "forager_person_id"}


@respx.mock
async def test_create_property_group_and_property_are_idempotent_on_conflict(hubspot):
    respx.post(f"{BASE}/crm/v3/properties/contacts/groups").mock(return_value=httpx.Response(409))
    route = respx.post(f"{BASE}/crm/v3/properties/contacts").mock(return_value=httpx.Response(409))

    created_group = await hubspot.create_property_group("contacts", "forager_enrichment", "Forager Enrichment")
    created = await hubspot.create_property("contacts", {"name": "forager_person_id"})

    assert created_group is False
    assert created is False
    assert body(route) == {"name": "forager_person_id"}
