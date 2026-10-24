import copy
import json
from pathlib import Path

import pytest

from app.mapping import map_company, normalize_domain, parse_location

ORG = json.loads((Path(__file__).parent / "fixtures" / "forager_organization.json").read_text())["search_results"][0]


def org(**overrides):
    data = copy.deepcopy(ORG)
    data.update(overrides)
    return data


def test_maps_all_supported_company_fields():
    assert map_company(ORG) == {
        "name": "Acme AI",
        "domain": "acme.ai",
        "website": "https://www.acme.ai/",
        "description": "Acme AI builds test fixtures.",
        "annualrevenue": "1000000000",
        "numberofemployees": "3500",
        "founded_year": "2015",
        "linkedin_company_page": "https://www.linkedin.com/company/acme-ai/",
        "address": "1 Test Street",
        "city": "San Francisco",
        "state": "CA",
        "zip": "94110",
        "country": "United States",
        "forager_organization_id": "501",
        "forager_legal_name": "Acme AI, Inc.",
        "forager_industry": "Research Services",
        "forager_employees_range": "1001-5000",
        "forager_operating_status": "active",
        "forager_keywords": "artificial intelligence, research",
        "forager_logo_url": "https://cdn.example.test/acme.png",
    }


def test_missing_values_are_omitted_not_blanked():
    sparse = org(description=None, employees_amount=None, finance_info={"revenue": None}, keywords=[], logo="")

    mapped = map_company(sparse)

    for key in ("description", "numberofemployees", "annualrevenue", "forager_keywords", "forager_logo_url"):
        assert key not in mapped


def test_zero_headcount_is_kept_as_a_real_value():
    assert map_company(org(employees_amount=0))["numberofemployees"] == "0"


def test_location_falls_back_when_no_addresses():
    mapped = map_company(org(addresses=[]))

    assert mapped["city"] == "San Francisco"
    assert mapped["state"] == "California"
    assert mapped["country"] == "United States"
    assert "address" not in mapped and "zip" not in mapped


def test_tolerates_malformed_nested_values():
    mapped = map_company(org(finance_info=None, linkedin_info=None, location=None, addresses=None, keywords=None))

    assert mapped["name"] == "Acme AI"
    assert "linkedin_company_page" not in mapped
    assert "city" not in mapped


def test_keywords_are_capped_at_20():
    keywords = [{"id": i, "name": f"kw{i}"} for i in range(30)]

    assert map_company(org(keywords=keywords))["forager_keywords"].count(",") == 19


@pytest.mark.parametrize(
    "location, expected",
    [
        (ORG["location"], ("San Francisco", "California", "United States")),
        ({"name": "Austin, Texas, United States", "osm_locations": []}, ("Austin", "Texas", "United States")),
        ({"name": "London, United Kingdom", "osm_locations": []}, ("London", None, "United Kingdom")),
        ({"name": "Germany", "osm_locations": []}, (None, None, "Germany")),
        (
            {"name": "x", "osm_locations": [{"name": "Bavaria", "place_type": "state"}, {"name": "Germany", "place_type": "country"}]},
            (None, "Bavaria", "Germany"),
        ),
        (None, (None, None, None)),
        ({}, (None, None, None)),
    ],
)
def test_parse_location(location, expected):
    assert parse_location(location) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("openai.com", "openai.com"),
        ("https://www.OpenAI.com/about", "openai.com"),
        ("http://openai.com:443", "openai.com"),
        ("  www.openai.com  ", "openai.com"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_domain(raw, expected):
    assert normalize_domain(raw) == expected
