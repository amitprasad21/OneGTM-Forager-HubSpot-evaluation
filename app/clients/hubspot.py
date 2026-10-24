"""HubSpot CRM client. Endpoints: docs/api-contracts.md §2."""

import asyncio

import httpx

from app.clients.http import Sleep, build_client, request_with_retry

BASE_URL = "https://api.hubapi.com"

# HUBSPOT_DEFINED association type ids for associations created with a record.
ASSOCIATION_TYPE_IDS = {
    ("contacts", "companies"): 1,  # contact -> primary company
    ("companies", "contacts"): 2,  # company -> primary contact
}


class HubSpotError(RuntimeError):
    def __init__(self, message: str, status_code: int, category: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.category = category


class HubSpotClient:
    def __init__(
        self,
        access_token: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        sleep: Sleep = asyncio.sleep,
    ):
        self._sleep = sleep
        self._http = http_client or build_client(
            BASE_URL, {"Authorization": f"Bearer {access_token}"}
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- objects ---------------------------------------------------------------

    async def get_object(self, object_type: str, object_id: str, properties: list[str]) -> dict | None:
        response = await self._request(
            "GET",
            f"/crm/v3/objects/{object_type}/{object_id}",
            params={"properties": ",".join(properties)},
            allow_not_found=True,
        )
        return None if response.status_code == 404 else response.json()

    async def update_object(self, object_type: str, object_id: str, properties: dict) -> dict:
        response = await self._request(
            "PATCH", f"/crm/v3/objects/{object_type}/{object_id}", json={"properties": properties}
        )
        return response.json()

    async def create_object(
        self,
        object_type: str,
        properties: dict,
        *,
        associate_with: tuple[str, str] | None = None,
    ) -> dict:
        payload: dict = {"properties": properties}
        if associate_with:
            to_type, to_id = associate_with
            payload["associations"] = [
                {
                    "to": {"id": str(to_id)},
                    "types": [
                        {
                            "associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": ASSOCIATION_TYPE_IDS[(object_type, to_type)],
                        }
                    ],
                }
            ]
        response = await self._request("POST", f"/crm/v3/objects/{object_type}", json=payload)
        return response.json()

    async def find_by_property(
        self, object_type: str, property_name: str, value: str, properties: list[str]
    ) -> dict | None:
        response = await self._request(
            "POST",
            f"/crm/v3/objects/{object_type}/search",
            json={
                "filterGroups": [
                    {"filters": [{"propertyName": property_name, "operator": "EQ", "value": value}]}
                ],
                "properties": properties,
                "limit": 1,
            },
        )
        results = response.json().get("results") or []
        return results[0] if results else None

    # --- associations ----------------------------------------------------------

    async def list_associated_ids(self, from_type: str, from_id: str, to_type: str) -> list[str]:
        ids: list[str] = []
        after: str | None = None
        while True:
            params = {"limit": 500, **({"after": after} if after else {})}
            response = await self._request(
                "GET", f"/crm/v4/objects/{from_type}/{from_id}/associations/{to_type}", params=params
            )
            data = response.json()
            ids.extend(str(item["toObjectId"]) for item in data.get("results", []))
            after = ((data.get("paging") or {}).get("next") or {}).get("after")
            if not after:
                return ids

    async def associate_default(self, from_type: str, from_id: str, to_type: str, to_id: str) -> None:
        await self._request(
            "PUT", f"/crm/v4/objects/{from_type}/{from_id}/associations/default/{to_type}/{to_id}"
        )

    # --- properties ------------------------------------------------------------

    async def get_property_names(self, object_type: str) -> set[str]:
        response = await self._request("GET", f"/crm/v3/properties/{object_type}")
        return {prop["name"] for prop in response.json().get("results", [])}

    async def create_property_group(self, object_type: str, name: str, label: str) -> bool:
        """Create a property group; returns False if it already exists."""
        response = await self._request(
            "POST",
            f"/crm/v3/properties/{object_type}/groups",
            json={"name": name, "label": label},
            allow_conflict=True,
        )
        return response.status_code != 409

    async def create_property(self, object_type: str, definition: dict) -> bool:
        """Create a property; returns False if it already exists."""
        response = await self._request(
            "POST", f"/crm/v3/properties/{object_type}", json=definition, allow_conflict=True
        )
        return response.status_code != 409

    # --- plumbing --------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        allow_not_found: bool = False,
        allow_conflict: bool = False,
        **kwargs,
    ) -> httpx.Response:
        response = await request_with_retry(self._http, method, path, sleep=self._sleep, **kwargs)
        if response.is_success:
            return response
        if (allow_not_found and response.status_code == 404) or (
            allow_conflict and response.status_code == 409
        ):
            return response
        category = None
        try:
            category = response.json().get("category")
        except ValueError:
            pass
        raise HubSpotError(
            f"HubSpot {method} {path} failed with HTTP {response.status_code} ({category or 'unknown'})",
            response.status_code,
            category,
        )
