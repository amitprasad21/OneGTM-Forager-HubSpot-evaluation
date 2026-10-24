from app.hubspot_properties import COMPANY_PROPERTIES, CONTACT_PROPERTIES, GROUP_NAME, ensure_properties


class RecordingHubSpot:
    def __init__(self, existing: dict[str, set[str]]):
        self.existing = existing
        self.groups: list[tuple[str, str]] = []
        self.created: list[tuple[str, dict]] = []

    async def create_property_group(self, object_type, name, label):
        self.groups.append((object_type, name))
        return True

    async def get_property_names(self, object_type):
        return set(self.existing.get(object_type, set()))

    async def create_property(self, object_type, definition):
        self.created.append((object_type, definition))
        return True


def names(definitions):
    return {d["name"] for d in definitions}


def test_all_custom_properties_are_prefixed_and_grouped():
    for definition in COMPANY_PROPERTIES + CONTACT_PROPERTIES:
        assert definition["name"].startswith("forager_")
        assert definition["groupName"] == GROUP_NAME
        assert {"label", "type", "fieldType"} <= definition.keys()


def test_mapped_custom_fields_have_definitions():
    assert {
        "forager_organization_id", "forager_legal_name", "forager_industry", "forager_employees_range",
        "forager_operating_status", "forager_keywords", "forager_logo_url",
        "forager_enrichment_status", "forager_enriched_at", "forager_enrichment_notes",
    } <= names(COMPANY_PROPERTIES)
    assert {
        "forager_person_id", "forager_company_domain", "forager_company_linkedin_url", "forager_alt_email",
        "forager_enrichment_status", "forager_enriched_at", "forager_enrichment_notes",
    } <= names(CONTACT_PROPERTIES)


def test_status_property_is_an_enumeration_with_all_statuses():
    status = next(d for d in COMPANY_PROPERTIES if d["name"] == "forager_enrichment_status")

    assert status["type"] == "enumeration"
    assert {o["value"] for o in status["options"]} == {"enriched", "partial", "not_found", "failed"}


async def test_creates_group_and_only_missing_properties():
    hubspot = RecordingHubSpot({"companies": {"forager_industry"}, "contacts": set()})

    summary = await ensure_properties(hubspot)

    assert ("companies", GROUP_NAME) in hubspot.groups and ("contacts", GROUP_NAME) in hubspot.groups
    created_company = {d["name"] for t, d in hubspot.created if t == "companies"}
    assert "forager_industry" not in created_company
    assert created_company == names(COMPANY_PROPERTIES) - {"forager_industry"}
    assert summary["companies"] == sorted(created_company)


async def test_extra_discussion_fields_only_when_requested():
    hubspot = RecordingHubSpot({})
    await ensure_properties(hubspot)
    assert "forager_about" not in {d["name"] for _, d in hubspot.created}

    hubspot = RecordingHubSpot({})
    await ensure_properties(hubspot, include_extra_fields=True)
    assert {"forager_headline", "forager_about"} <= {d["name"] for _, d in hubspot.created}


async def test_second_run_creates_nothing():
    everything = {"companies": names(COMPANY_PROPERTIES), "contacts": names(CONTACT_PROPERTIES)}
    hubspot = RecordingHubSpot(everything)

    summary = await ensure_properties(hubspot)

    assert hubspot.created == []
    assert summary == {"companies": [], "contacts": []}
