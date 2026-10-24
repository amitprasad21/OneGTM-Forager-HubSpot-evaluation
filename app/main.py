"""FastAPI application: health, HubSpot webhooks and operator endpoints."""

import asyncio
import hmac
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.config import settings as default_settings
from app.container import Container, build_container
from app.log import configure_logging, get_logger, log_event
from app.mapping import normalize_domain
from app.title_filter import TitleFilter
from app.webhooks import PayloadError, SignatureError, parse_events, verify_signature
from app.worker import Worker

log = get_logger(__name__)

STALE_JOB_LEASE_SECONDS = 600


class DiscoverRequest(BaseModel):
    domain: str
    include_titles: list[str] | None = None
    exclude_titles: list[str] | None = None
    limit: int = Field(default=5, ge=1, le=25)
    company_id: str | None = None  # when set, create + enrich + associate the contacts

    @field_validator("domain")
    @classmethod
    def _valid_domain(cls, value: str) -> str:
        domain = normalize_domain(value)
        if not domain:
            raise ValueError("domain is required")
        return domain


def create_app(container: Container | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal container
        if container is None:
            configure_logging(default_settings.log_level)
            default_settings.validate_required()
            container = build_container(default_settings)
        app.state.container = container

        requeued = container.store.requeue_stale(STALE_JOB_LEASE_SECONDS)
        await _cap_budget_by_live_balance(container)
        log_event(log, "app.started", requeued_jobs=requeued, credit_budget=container.ledger.budget)

        stop = asyncio.Event()
        task = None
        if container.settings.worker_enabled:
            task = asyncio.create_task(Worker(container.store, container.automation).run_forever(stop))
        try:
            yield
        finally:
            stop.set()
            if task:
                await task
            await container.aclose()

    app = FastAPI(title="Forager × HubSpot Enrichment", version="1.0.0", lifespan=lifespan)

    def get_container(request: Request) -> Container:
        return request.app.state.container

    def require_admin(
        x_admin_key: str = Header(default=""), container: Container = Depends(get_container)
    ) -> None:
        expected = container.settings.admin_api_key.get_secret_value()
        if not expected or not hmac.compare_digest(x_admin_key.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="invalid admin key")

    @app.get("/")
    def root():
        return {"service": "Forager HubSpot Enrichment", "status": "running", "docs": "/docs"}

    @app.get("/health")
    def health(container: Container = Depends(get_container)):
        try:
            db_ok = container.store.ping()
            queue = container.store.counts()
        except Exception:  # noqa: BLE001
            db_ok, queue = False, {}
        return {
            "status": "ok",
            "forager_configured": container.settings.forager_configured,
            "hubspot_configured": container.settings.hubspot_configured,
            "db_ok": db_ok,
            "queue": queue,
        }

    @app.post("/webhooks/hubspot")
    async def hubspot_webhook(request: Request, container: Container = Depends(get_container)):
        body = await request.body()
        uri = container.settings.webhook_base_url + request.url.path
        if request.url.query:
            uri += f"?{request.url.query}"
        try:
            version = verify_signature(
                request.method,
                uri,
                body,
                request.headers,
                container.settings.hubspot_client_secret.get_secret_value(),
                now_ms=int(time.time() * 1000),
            )
        except SignatureError as error:
            log_event(log, "webhook.rejected", reason=str(error))
            raise HTTPException(status_code=401, detail="invalid signature") from None
        try:
            events = parse_events(body)
        except PayloadError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None

        queued = duplicates = 0
        for event in events:
            if not container.store.record_event(event.event_key):
                duplicates += 1
                continue
            if container.store.enqueue(f"{event.object_type}_created", event.object_id) is None:
                duplicates += 1
            else:
                queued += 1
        log_event(
            log, "webhook.accepted", signature_version=version, received=len(events), queued=queued, duplicates=duplicates
        )
        return {"received": len(events), "queued": queued, "duplicates": duplicates}

    # --- operator endpoints --------------------------------------------------------

    @app.post("/admin/enrich/company/{company_id}", dependencies=[Depends(require_admin)])
    async def admin_enrich_company(company_id: str, force: bool = False, container: Container = Depends(get_container)):
        return await container.automation.company_created(company_id, force=force)

    @app.post("/admin/enrich/contact/{contact_id}", dependencies=[Depends(require_admin)])
    async def admin_enrich_contact(contact_id: str, force: bool = False, container: Container = Depends(get_container)):
        return await container.automation.contact_created(contact_id, force=force)

    @app.post("/admin/discover", dependencies=[Depends(require_admin)])
    async def admin_discover(request: DiscoverRequest, container: Container = Depends(get_container)):
        default = container.automation.default_title_filter
        title_filter = TitleFilter(
            request.include_titles if request.include_titles is not None else default.include,
            request.exclude_titles if request.exclude_titles is not None else default.exclude,
        )
        if request.company_id:
            results = await container.automation.discover_for_company(
                request.company_id, request.domain, title_filter, request.limit
            )
            return {
                "filter": title_filter.describe(),
                "created": [{"id": r.object_id, "status": r.status, "missing": r.missing} for r in results],
            }
        candidates = await container.automation.preview_discovery(request.domain, title_filter, request.limit)
        return {"filter": title_filter.describe(), "candidates": [_candidate(c) for c in candidates]}

    @app.post("/admin/reconcile", dependencies=[Depends(require_admin)])
    async def admin_reconcile(hours: int = 24, container: Container = Depends(get_container)):
        since = int((time.time() - hours * 3600) * 1000)
        counts = {}
        for object_type, kind in (("companies", "company_created"), ("contacts", "contact_created")):
            ids = await container.hubspot.search_ids_without_property(
                object_type, "forager_enrichment_status", created_after_ms=since
            )
            counts[object_type] = sum(1 for object_id in ids if container.store.enqueue(kind, object_id))
        log_event(log, "reconcile.queued", **counts)
        return counts

    @app.get("/admin/jobs", dependencies=[Depends(require_admin)])
    def admin_jobs(limit: int = 20, container: Container = Depends(get_container)):
        return {"counts": container.store.counts(), "jobs": [vars(job) for job in container.store.recent(limit)]}

    @app.get("/admin/credits", dependencies=[Depends(require_admin)])
    def admin_credits(container: Container = Depends(get_container)):
        return container.ledger.summary()

    return app


def _candidate(person: dict) -> dict:
    role = (person.get("roles") or [{}])[0]
    return {
        "forager_person_id": person.get("id"),
        "name": person.get("full_name"),
        "job_title": role.get("role_title"),
        "company": (role.get("organization") or {}).get("name"),
        "linkedin_url": (person.get("linkedin_info") or {}).get("public_profile_url"),
        "location": (person.get("location") or {}).get("name"),
    }


async def _cap_budget_by_live_balance(container: Container) -> None:
    """On an ephemeral disk the ledger may reset; never budget above Forager's real balance."""
    get_balance = getattr(container.forager, "get_credit_balance", None)
    if get_balance is None:
        return
    try:
        balance = await get_balance()
    except Exception as error:  # noqa: BLE001 - startup must not fail on this
        log_event(log, "credits.balance_unavailable", error=type(error).__name__)
        return
    if balance is not None:
        container.ledger.budget = min(container.ledger.budget, container.ledger.spent + balance)
        log_event(log, "credits.budget_capped", balance=balance, budget=container.ledger.budget)


app = create_app()
