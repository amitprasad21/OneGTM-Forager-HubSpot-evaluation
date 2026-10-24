import base64
import copy
import hashlib
import hmac
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import Container
from app.jobs import JobStore, SqliteCreditLedger
from app.main import create_app
from app.services.automation import EnrichmentAutomation
from app.services.contact_enrichment import ContactLookupOptions
from app.title_filter import TitleFilter
from tests.fakes import FakeForager, FakeHubSpot
from tests.test_discovery_service import role

ORG = json.loads((Path(__file__).parent / "fixtures" / "forager_organization.json").read_text())["search_results"][0]
SECRET = "client-secret"
ADMIN = "admin-key"
BASE_URL = "https://svc.onrender.com"


def signed_headers(body: bytes, path="/webhooks/hubspot"):
    timestamp = str(int(time.time() * 1000))
    message = f"POST{BASE_URL}{path}{body.decode()}{timestamp}".encode()
    signature = base64.b64encode(hmac.new(SECRET.encode(), message, hashlib.sha256).digest()).decode()
    return {
        "X-HubSpot-Signature-v3": signature,
        "X-HubSpot-Request-Timestamp": timestamp,
        "Content-Type": "application/json",
    }


@pytest.fixture
def container(tmp_path):
    settings = Settings(
        _env_file=None,
        forager_api_key="k",
        forager_account_id="1234",
        hubspot_access_token="t",
        hubspot_client_secret=SECRET,
        admin_api_key=ADMIN,
        public_base_url=BASE_URL,
        worker_enabled=False,
    )
    store = JobStore(str(tmp_path / "app.db"))
    hubspot = FakeHubSpot()
    forager = FakeForager()
    forager.organizations = [copy.deepcopy(ORG)]
    forager.role_results = [role(1, "VP Engineering"), role(2, "Software Engineer")]
    forager.work_emails = {"p-1": "p1@acme.ai", "p-2": "p2@acme.ai"}
    automation = EnrichmentAutomation(
        hubspot,
        forager,
        title_filter=TitleFilter(include=["VP"]),
        max_contacts=5,
        contact_options=lambda: ContactLookupOptions(max_phone_lookups=2),
    )
    container = Container(
        settings=settings,
        store=store,
        hubspot=hubspot,
        forager=forager,
        ledger=SqliteCreditLedger(store, budget=45),
        automation=automation,
    )
    yield container
    store.close()


@pytest.fixture
def client(container):
    with TestClient(create_app(container)) as client:
        yield client


def test_health_reports_configuration_without_secrets(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["forager_configured"] is True and body["hubspot_configured"] is True
    assert body["db_ok"] is True
    assert body["queue"] == {"queued": 0, "running": 0, "done": 0, "failed": 0}
    assert SECRET not in response.text and ADMIN not in response.text


def test_webhook_with_valid_signature_queues_jobs(client, container):
    body = json.dumps(
        [
            {"eventId": 1, "subscriptionType": "object.creation", "objectTypeId": "0-2", "objectId": 101},
            {"eventId": 2, "subscriptionType": "object.creation", "objectTypeId": "0-1", "objectId": 5},
        ]
    ).encode()

    response = client.post("/webhooks/hubspot", content=body, headers=signed_headers(body))

    assert response.status_code == 200
    assert response.json() == {"received": 2, "queued": 2, "duplicates": 0}
    assert [(j.kind, j.object_id) for j in container.store.recent()] == [
        ("contact_created", "5"),
        ("company_created", "101"),
    ]


def test_duplicate_event_is_acknowledged_but_not_requeued(client, container):
    body = b'[{"eventId": 7, "subscriptionType": "contact.creation", "objectId": 5}]'

    client.post("/webhooks/hubspot", content=body, headers=signed_headers(body))
    response = client.post("/webhooks/hubspot", content=body, headers=signed_headers(body))

    assert response.json() == {"received": 1, "queued": 0, "duplicates": 1}
    assert len(container.store.recent()) == 1


def test_webhook_with_bad_signature_is_rejected(client, container):
    body = b'[{"eventId": 1, "subscriptionType": "contact.creation", "objectId": 5}]'
    headers = signed_headers(body)
    headers["X-HubSpot-Signature-v3"] = "forged"

    response = client.post("/webhooks/hubspot", content=body, headers=headers)

    assert response.status_code == 401
    assert container.store.recent() == []


def test_webhook_without_signature_is_rejected(client):
    assert client.post("/webhooks/hubspot", content=b"[]").status_code == 401


def test_webhook_with_malformed_body_is_400(client):
    body = b'{"not": "a list"}'
    assert client.post("/webhooks/hubspot", content=body, headers=signed_headers(body)).status_code == 400


def test_admin_endpoints_require_admin_key(client):
    assert client.get("/admin/jobs").status_code == 401
    assert client.get("/admin/jobs", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert client.get("/admin/jobs", headers={"X-Admin-Key": ADMIN}).status_code == 200


def test_admin_enrich_company_runs_full_flow(client, container):
    container.hubspot.add("companies", "101", domain="acme.ai")

    response = client.post("/admin/enrich/company/101", headers={"X-Admin-Key": ADMIN})

    assert response.status_code == 200
    body = response.json()
    assert body["company_status"] == "enriched"
    assert body["mode"] == "discovered"
    assert len(body["contacts"]) == 1  # only the VP passes the default filter


def test_admin_enrich_contact_with_force(client, container):
    container.forager.people = {"jane": {"id": 9, "first_name": "Jane", "last_name": "Doe", "roles": []}}
    container.hubspot.add(
        "contacts", "5", hs_linkedin_url="https://www.linkedin.com/in/jane/", forager_enrichment_status="partial"
    )

    skipped = client.post("/admin/enrich/contact/5", headers={"X-Admin-Key": ADMIN}).json()
    forced = client.post("/admin/enrich/contact/5?force=true", headers={"X-Admin-Key": ADMIN}).json()

    assert skipped["status"] == "skipped"
    assert forced["status"] == "partial"


def test_admin_discover_preview_applies_title_filter_without_writes(client, container):
    response = client.post(
        "/admin/discover",
        headers={"X-Admin-Key": ADMIN},
        json={"domain": "https://www.acme.ai", "include_titles": ["Engineer"], "exclude_titles": [], "limit": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filter"] == "include: Engineer; exclude: none"
    assert [c["job_title"] for c in body["candidates"]] == ["Software Engineer"]
    assert body["candidates"][0]["linkedin_url"] == "https://www.linkedin.com/in/p-2/"
    assert container.hubspot.created == []
    assert container.forager.called("find_work_email") == []


def test_admin_discover_rejects_missing_domain(client):
    response = client.post("/admin/discover", headers={"X-Admin-Key": ADMIN}, json={"domain": " "})
    assert response.status_code == 422


def test_admin_reconcile_requeues_records_without_status(client, container):
    async def unprocessed(object_type, property_name, *, created_after_ms):
        return ["101"] if object_type == "companies" else ["5", "6"]

    container.hubspot.search_ids_without_property = unprocessed

    response = client.post("/admin/reconcile?hours=24", headers={"X-Admin-Key": ADMIN})

    assert response.json() == {"companies": 1, "contacts": 2}
    assert len(container.store.recent()) == 3


def test_admin_credits_reports_ledger(client, container):
    container.ledger.record(5, "work_email")

    body = client.get("/admin/credits", headers={"X-Admin-Key": ADMIN}).json()

    assert body["spent"] == 5 and body["budget"] == 45


def test_startup_caps_budget_by_live_forager_balance(container):
    async def balance():
        return 10

    container.forager.get_credit_balance = balance
    container.ledger.record(3, "organization_search")

    with TestClient(create_app(container)):
        assert container.ledger.budget == 13  # already spent 3 + 10 still available < configured 45


def test_startup_survives_balance_lookup_failure(container):
    async def broken():
        raise RuntimeError("forager down")

    container.forager.get_credit_balance = broken

    with TestClient(create_app(container)) as client:
        assert client.get("/health").status_code == 200
        assert container.ledger.budget == 45
