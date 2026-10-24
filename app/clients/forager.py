"""Forager API client. Endpoints and shapes: docs/api-contracts.md §1."""

import asyncio
from typing import Any

import httpx

from app.clients.http import Sleep, build_client, request_with_retry
from app.credits import (
    COST_ORGANIZATION_SEARCH,
    COST_PERSON_DETAIL,
    COST_PERSON_ROLE_SEARCH,
    COST_PERSONAL_EMAIL,
    COST_PHONE,
    COST_REVERSE_EMAIL,
    COST_WORK_EMAIL,
    CreditLedger,
)

BASE_URL = "https://api-v2.forager.ai"
WORK_EMAIL_TERMINAL = {"completed", "failed"}
GOOD_VERDICTS = {"valid", "deliverable", "verified"}
BAD_VERDICTS = {"invalid", "undeliverable"}


class ForagerError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ForagerAuthError(ForagerError):
    pass


class ForagerClient:
    def __init__(
        self,
        api_key: str,
        account_id: str,
        ledger: CreditLedger,
        *,
        http_client: httpx.AsyncClient | None = None,
        sleep: Sleep = asyncio.sleep,
        work_email_poll_interval: float = 2.0,
        work_email_max_wait: float = 90.0,
    ):
        self._account_id = account_id
        self._ledger = ledger
        self._sleep = sleep
        self._http = http_client or build_client(BASE_URL, {"X-API-KEY": api_key})
        self._poll_interval = work_email_poll_interval
        self._max_wait = work_email_max_wait

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- organizations --------------------------------------------------------

    async def search_organizations(
        self,
        *,
        domains: list[str] | None = None,
        organization_ids: list[int] | None = None,
        linkedin_public_identifiers: list[str] | None = None,
        page: int = 1,
    ) -> dict:
        payload = _compact(
            domains=domains,
            organization_ids=organization_ids,
            linkedin_public_identifiers=linkedin_public_identifiers,
            page=page,
        )
        return await self._charged_search("organization_search/", payload, COST_ORGANIZATION_SEARCH)

    async def autocomplete_organizations(self, query: str, page: int = 1) -> list[dict]:
        response = await self._request(
            "GET", self._ds("autocomplete/organizations/"), params={"q": query, "page": page}
        )
        data = _json_or_none(response) or {}
        return data.get("results") or []

    # --- people ----------------------------------------------------------------

    async def search_person_roles(self, *, page: int = 1, **filters: Any) -> dict:
        payload = _compact(**filters, page=page)
        return await self._charged_search("person_role_search/", payload, COST_PERSON_ROLE_SEARCH)

    async def get_person_detail(
        self, *, person_id: int | None = None, linkedin_slug: str | None = None
    ) -> dict | None:
        payload = _person_identifier(person_id, linkedin_slug)
        self._ledger.ensure_available(COST_PERSON_DETAIL)
        response = await self._request("POST", self._ds("person_detail_lookup/"), json=payload)
        person = _json_or_none(response)
        if not person:
            return None
        self._ledger.record(COST_PERSON_DETAIL, "person_detail")
        return person

    async def reverse_lookup_email(self, email: str) -> dict | None:
        self._ledger.ensure_available(COST_REVERSE_EMAIL)
        response = await self._request(
            "POST", self._ds("person_detail_reverse_lookup/by_email/"), json={"email": email}
        )
        person = _json_or_none(response)
        if not person:
            return None
        self._ledger.record(COST_REVERSE_EMAIL, "reverse_email")
        return person

    # --- contact data ----------------------------------------------------------

    async def find_phone(
        self, *, person_id: int | None = None, linkedin_slug: str | None = None
    ) -> str | None:
        payload = _person_identifier(person_id, linkedin_slug)
        self._ledger.ensure_available(COST_PHONE)
        response = await self._request(
            "POST", self._ds("person_contacts_lookup/phone_numbers/"), json=payload
        )
        numbers = [
            item.get("phone_number")
            for item in _json_or_none(response) or []
            if isinstance(item, dict) and item.get("phone_number")
        ]
        if not numbers:
            return None
        self._ledger.record(COST_PHONE, "phone")
        return numbers[0]

    async def find_personal_email(
        self, *, person_id: int | None = None, linkedin_slug: str | None = None
    ) -> str | None:
        payload = _person_identifier(person_id, linkedin_slug)
        self._ledger.ensure_available(COST_PERSONAL_EMAIL)
        response = await self._request(
            "POST", self._ds("person_contacts_lookup/personal_emails/"), json=payload
        )
        items = [i for i in _json_or_none(response) or [] if isinstance(i, dict) and i.get("email")]
        if items:
            # Forager charges whenever addresses are returned, even if we discard them.
            self._ledger.record(COST_PERSONAL_EMAIL, "personal_email")
        for status in ("valid", "risky", "unknown"):
            for item in items:
                if item.get("validation_status") == status:
                    return item["email"]
        return None

    async def find_work_email(
        self,
        *,
        linkedin_slug: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        domain: str | None = None,
    ) -> str | None:
        if linkedin_slug:
            payload = {"linkedin_public_identifier": linkedin_slug}
        elif first_name and last_name and domain:
            payload = {"first_name": first_name, "last_name": last_name, "domain": domain}
        else:
            raise ValueError("work email lookup needs linkedin_slug or first_name + last_name + domain")

        self._ledger.ensure_available(COST_WORK_EMAIL)
        response = await self._request("POST", self._v2("person_contacts_lookup/work_emails/"), json=payload)
        job_id = (_json_or_none(response) or {}).get("job_id")
        if not job_id:
            raise ForagerError("work email lookup did not return a job_id", response.status_code)

        job = await self._poll_work_email(job_id)
        if not job or job.get("status") != "completed" or job.get("result") != "found":
            return None
        email = _pick_work_email(job.get("emails") or [])
        if email:
            self._ledger.record(COST_WORK_EMAIL, "work_email")
        return email

    async def _poll_work_email(self, job_id: str) -> dict | None:
        waited = 0.0
        while True:
            response = await self._request(
                "GET", self._v2(f"person_contacts_lookup/work_emails/{job_id}/")
            )
            job = _json_or_none(response) or {}
            if job.get("status") in WORK_EMAIL_TERMINAL:
                return job
            delay = _retry_after(response) or self._poll_interval
            if waited + delay > self._max_wait:
                return None
            await self._sleep(delay)
            waited += delay

    # --- plumbing --------------------------------------------------------------

    def _ds(self, path: str) -> str:
        return f"/api/{self._account_id}/datastorage/{path}"

    def _v2(self, path: str) -> str:
        return f"/api/v2/{self._account_id}/datastorage/{path}"

    async def _charged_search(self, path: str, payload: dict, cost: int) -> dict:
        self._ledger.ensure_available(cost)
        response = await self._request("POST", self._ds(path), json=payload)
        self._ledger.record(cost, path.rstrip("/"))
        return _json_or_none(response) or {"search_results": [], "total_search_results": 0}

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = await request_with_retry(self._http, method, path, sleep=self._sleep, **kwargs)
        if response.status_code in (401, 403):
            raise ForagerAuthError(f"Forager rejected credentials (HTTP {response.status_code})", response.status_code)
        if response.status_code == 404 or response.is_success:
            return response
        raise ForagerError(
            f"Forager {method} {path} failed with HTTP {response.status_code}", response.status_code
        )


def _compact(**fields: Any) -> dict:
    return {key: value for key, value in fields.items() if value is not None}


def _person_identifier(person_id: int | None, linkedin_slug: str | None) -> dict:
    if person_id is not None:
        return {"person_id": person_id}
    if linkedin_slug:
        return {"linkedin_public_identifier": linkedin_slug}
    raise ValueError("person_id or linkedin_slug is required")


def _json_or_none(response: httpx.Response) -> Any:
    """Parse JSON; 404s and empty bodies (documented for 'nothing found') become None."""
    if response.status_code == 404 or not response.content.strip():
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return None


def _pick_work_email(items: list) -> str | None:
    """Items may be strings, [email, verdict] pairs, or objects (schema is ambiguous)."""
    candidates: list[tuple[str, str | None]] = []
    for item in items:
        if isinstance(item, str):
            candidates.append((item, None))
        elif isinstance(item, (list, tuple)) and item and isinstance(item[0], str):
            candidates.append((item[0], item[1] if len(item) > 1 else None))
        elif isinstance(item, dict) and item.get("email"):
            verdict = item.get("verdict") or item.get("status") or item.get("validation_status")
            candidates.append((item["email"], verdict))

    for email, verdict in candidates:
        if verdict and str(verdict).lower() in GOOD_VERDICTS:
            return email
    for email, verdict in candidates:
        if not verdict or str(verdict).lower() not in BAD_VERDICTS:
            return email
    return None
