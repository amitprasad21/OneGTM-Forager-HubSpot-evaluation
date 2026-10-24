import copy
import json
from pathlib import Path

import pytest

from app.mapping import current_role, linkedin_slug, map_contact, person_from_role_result

FIXTURES = Path(__file__).parent / "fixtures"
PERSON = json.loads((FIXTURES / "forager_person.json").read_text())
ROLE_RESULT = json.loads((FIXTURES / "forager_role_search.json").read_text())["search_results"][0]


def person(**overrides):
    data = copy.deepcopy(PERSON)
    data.update(overrides)
    return data


def test_maps_required_contact_fields():
    assert map_contact(PERSON) == {
        "firstname": "Jane",
        "lastname": "Doe",
        "hs_linkedin_url": "https://www.linkedin.com/in/jane-doe-test/",
        "jobtitle": "VP Engineering",
        "company": "Acme AI",
        "forager_company_domain": "acme.ai",
        "forager_company_linkedin_url": "https://www.linkedin.com/company/acme-ai/",
        "city": "San Francisco",
        "state": "California",
        "country": "United States",
        "forager_person_id": "9001",
    }


def test_extra_fields_only_when_enabled():
    mapped = map_contact(PERSON, include_extra_fields=True)

    assert mapped["forager_headline"] == "VP Engineering at Acme AI"
    assert mapped["forager_about"] == "Builds reliable systems. (synthetic test profile)"
    assert mapped["forager_skills"] == "Python, Distributed Systems"
    assert "forager_about" not in map_contact(PERSON)


def test_current_role_prefers_most_recent_current_role():
    assert current_role(PERSON)["role_title"] == "VP Engineering"


def test_current_role_prefers_target_domain_when_given():
    assert current_role(PERSON, prefer_domain="side.example")["role_title"] == "Advisor"


def test_no_current_role_means_no_title_or_employer():
    past_only = person(roles=[r | {"is_current": False} for r in PERSON["roles"]])

    mapped = map_contact(past_only)

    assert current_role(past_only) is None
    for key in ("jobtitle", "company", "forager_company_domain", "forager_company_linkedin_url"):
        assert key not in mapped


def test_missing_and_malformed_fields_are_omitted():
    sparse = person(last_name=None, linkedin_info=None, location=None, roles=None)

    mapped = map_contact(sparse)

    assert mapped == {"firstname": "Jane", "forager_person_id": "9001"}


def test_person_from_role_result_builds_detail_shaped_person():
    built = person_from_role_result(ROLE_RESULT)

    assert built["id"] == 9001
    assert built["roles"] == [
        {
            "role_title": "VP Engineering",
            "is_current": True,
            "start_date": "2020-01-01",
            "organization": ROLE_RESULT["organization"],
        }
    ]
    mapped = map_contact(built)
    assert mapped["jobtitle"] == "VP Engineering"
    assert mapped["company"] == "Acme AI"
    assert mapped["city"] == "San Francisco"


@pytest.mark.parametrize(
    "value, expected",
    [
        ("https://www.linkedin.com/in/jane-doe-test/", "jane-doe-test"),
        ("http://linkedin.com/in/Jane-Doe?trk=abc", "Jane-Doe"),
        ("https://uk.linkedin.com/in/j%C3%A1ne/", "jáne"),
        ("linkedin.com/in/jane", "jane"),
        ("https://www.linkedin.com/company/acme-ai/", None),
        ("jane-doe", None),
        ("", None),
        (None, None),
    ],
)
def test_linkedin_slug(value, expected):
    assert linkedin_slug(value) == expected
