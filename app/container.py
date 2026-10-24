"""Wires settings, storage, API clients and services together."""

from dataclasses import dataclass

from app.clients.forager import ForagerClient
from app.clients.hubspot import HubSpotClient
from app.config import Settings
from app.jobs import JobStore, SqliteCreditLedger
from app.services.automation import EnrichmentAutomation
from app.services.contact_enrichment import ContactLookupOptions
from app.title_filter import TitleFilter


@dataclass
class Container:
    settings: Settings
    store: JobStore
    hubspot: object
    forager: object
    ledger: SqliteCreditLedger
    automation: EnrichmentAutomation

    async def aclose(self) -> None:
        for client in (self.hubspot, self.forager):
            close = getattr(client, "aclose", None)
            if close:
                await close()
        self.store.close()


def build_container(settings: Settings) -> Container:
    store = JobStore(settings.database_path)
    ledger = SqliteCreditLedger(store, budget=settings.forager_credit_budget)
    hubspot = HubSpotClient(settings.hubspot_access_token.get_secret_value())
    forager = ForagerClient(
        settings.forager_api_key.get_secret_value(), settings.forager_account_id, ledger
    )
    automation = EnrichmentAutomation(
        hubspot,
        forager,
        title_filter=TitleFilter(settings.discovery_titles, settings.discovery_exclude_titles),
        max_contacts=settings.discovery_max_contacts,
        contact_options=lambda: ContactLookupOptions(
            enable_phone=settings.enable_phone_lookup,
            enable_personal_email=settings.enable_personal_email_lookup,
            include_extra_fields=settings.enrich_extra_fields,
            max_phone_lookups=settings.max_phone_lookups_per_job,
        ),
    )
    return Container(settings, store, hubspot, forager, ledger, automation)
