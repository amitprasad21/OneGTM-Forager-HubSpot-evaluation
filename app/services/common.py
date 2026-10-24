"""Shared enrichment status values and result type."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

ENRICHED = "enriched"
PARTIAL = "partial"
NOT_FOUND = "not_found"
FAILED = "failed"
MISSING = "missing"  # HubSpot record does not exist (deleted before processing)
SKIPPED = "skipped"  # already enriched; nothing to do

STATUS_PROPERTY = "forager_enrichment_status"
ENRICHED_AT_PROPERTY = "forager_enriched_at"
NOTES_PROPERTY = "forager_enrichment_notes"

Clock = Callable[[], int]


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class EnrichmentResult:
    object_id: str
    status: str
    missing: list[str] = field(default_factory=list)
    domain: str | None = None
    organization: dict | None = None
    person: dict | None = None


def status_properties(status: str, clock: Clock, notes: str = "") -> dict[str, str]:
    return {
        STATUS_PROPERTY: status,
        ENRICHED_AT_PROPERTY: str(clock()),
        NOTES_PROPERTY: notes,
    }
