"""Custom HubSpot properties used by the enrichment (docs/data-mapping.md)."""

GROUP_NAME = "forager_enrichment"
GROUP_LABEL = "Forager Enrichment"


def _text(name: str, label: str, multiline: bool = False) -> dict:
    return {
        "name": name,
        "label": label,
        "type": "string",
        "fieldType": "textarea" if multiline else "text",
        "groupName": GROUP_NAME,
    }


def _status_properties() -> list[dict]:
    return [
        {
            "name": "forager_enrichment_status",
            "label": "Forager enrichment status",
            "type": "enumeration",
            "fieldType": "select",
            "groupName": GROUP_NAME,
            "options": [
                {"label": "Enriched", "value": "enriched", "displayOrder": 0},
                {"label": "Partial", "value": "partial", "displayOrder": 1},
                {"label": "Not found", "value": "not_found", "displayOrder": 2},
                {"label": "Failed", "value": "failed", "displayOrder": 3},
            ],
        },
        {
            "name": "forager_enriched_at",
            "label": "Forager enriched at",
            "type": "datetime",
            "fieldType": "date",
            "groupName": GROUP_NAME,
        },
        _text("forager_enrichment_notes", "Forager enrichment notes", multiline=True),
    ]


COMPANY_PROPERTIES = [
    _text("forager_organization_id", "Forager organization ID"),
    _text("forager_legal_name", "Legal name (Forager)"),
    _text("forager_industry", "Industry (Forager)"),
    _text("forager_employees_range", "Employee range (Forager)"),
    _text("forager_operating_status", "Operating status (Forager)"),
    _text("forager_keywords", "Keywords (Forager)", multiline=True),
    _text("forager_logo_url", "Logo URL (Forager)"),
    *_status_properties(),
]

CONTACT_PROPERTIES = [
    _text("forager_person_id", "Forager person ID"),
    _text("forager_company_domain", "Employer domain (Forager)"),
    _text("forager_company_linkedin_url", "Employer LinkedIn URL (Forager)"),
    _text("forager_alt_email", "Alternative email (Forager)"),
    *_status_properties(),
]

# Nice-to-have fields flagged for discussion; created only when ENRICH_EXTRA_FIELDS is on.
CONTACT_EXTRA_PROPERTIES = [
    _text("forager_headline", "LinkedIn headline (Forager)"),
    _text("forager_about", "LinkedIn About (Forager)", multiline=True),
    _text("forager_skills", "Skills (Forager)", multiline=True),
]


async def ensure_properties(hubspot, include_extra_fields: bool = False) -> dict[str, list[str]]:
    """Create the property group and any missing custom properties. Safe to re-run."""
    wanted = {
        "companies": COMPANY_PROPERTIES,
        "contacts": CONTACT_PROPERTIES + (CONTACT_EXTRA_PROPERTIES if include_extra_fields else []),
    }
    created: dict[str, list[str]] = {}
    for object_type, definitions in wanted.items():
        await hubspot.create_property_group(object_type, GROUP_NAME, GROUP_LABEL)
        existing = await hubspot.get_property_names(object_type)
        created[object_type] = []
        for definition in definitions:
            if definition["name"] not in existing:
                await hubspot.create_property(object_type, definition)
                created[object_type].append(definition["name"])
        created[object_type].sort()
    return created
