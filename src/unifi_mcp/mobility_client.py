"""UniFi Mobility API client (cloud).

Proxy API for UniFi Mobile Router (UMR) devices exposed through the
cloudservice-apis gateway at https://api.ui.com/v1/mobility.

Authentication uses the ``X-API-Key`` header. The key must carry the
``mobility`` app scope (read:mobility for GETs, write:mobility for PUTs).
"""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MOBILITY_API_BASE_URL = "https://api.ui.com/v1/mobility"


class MobilityApiError(Exception):
    """Raised when the UniFi Mobility API returns an error."""

    def __init__(self, status_code: int, message: str, trace_id: str | None = None):
        self.status_code = status_code
        self.message = message
        self.trace_id = trace_id
        super().__init__(f"UniFi Mobility API error {status_code}: {message}")


class MobilityClient:
    """Async client for the UniFi Mobility API (cloud, v1).

    Mobility is a cloud API like Site Manager, so it reuses the account
    API key by default. Override with UNIFI_MOBILITY_API_KEY if the
    mobility scope lives on a separate key.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ):
        self.api_key = (
            api_key
            or os.environ.get("UNIFI_MOBILITY_API_KEY", "")
            or os.environ.get("UNIFI_API_KEY", "")
        )
        if not self.api_key:
            raise ValueError(
                "UniFi API key is required. Set UNIFI_MOBILITY_API_KEY "
                "or UNIFI_API_KEY environment variable, or pass api_key parameter."
            )
        resolved_base_url = (
            base_url
            or os.environ.get("UNIFI_MOBILITY_API_BASE_URL")
            or MOBILITY_API_BASE_URL
        )
        resolved_timeout = timeout or float(os.environ.get("UNIFI_API_TIMEOUT", "30"))
        self._client = httpx.AsyncClient(
            base_url=resolved_base_url.rstrip("/"),
            headers={
                "X-API-KEY": self.api_key,
                "Accept": "application/json",
            },
            timeout=resolved_timeout,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to the Mobility API.

        PUT endpoints return 204 with an empty body; those are mapped to
        a ``{"status": "success"}`` sentinel.
        """
        response = await self._client.request(
            method, path, params=params, json=json_body
        )

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            raise MobilityApiError(
                429, f"Rate limited. Retry after {retry_after} seconds."
            )

        if response.status_code == 204:
            return {"status": "success"}

        data = response.json()
        trace_id = data.get("traceId") if isinstance(data, dict) else None

        if response.status_code >= 400:
            message = (
                data.get("message", response.text)
                if isinstance(data, dict)
                else response.text
            )
            raise MobilityApiError(response.status_code, message, trace_id=trace_id)

        return data

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def _put(
        self, path: str, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request("PUT", path, json_body=json_body)

    @staticmethod
    def _page_params(limit: int = 200, offset: int = 0) -> dict[str, Any]:
        return {"limit": limit, "offset": offset}

    # --- Workspaces ---

    async def list_workspaces(self) -> dict[str, Any]:
        """GET /workspaces"""
        return await self._get("/workspaces")

    async def list_workspace_admins(self, workspace_id: str) -> dict[str, Any]:
        """GET /workspaces/{workspaceID}/admins"""
        return await self._get(f"/workspaces/{workspace_id}/admins")

    # --- Devices ---

    async def list_devices(
        self, workspace_id: str, limit: int = 200, offset: int = 0
    ) -> dict[str, Any]:
        """GET /workspaces/{workspaceID}/devices"""
        return await self._get(
            f"/workspaces/{workspace_id}/devices",
            params=self._page_params(limit, offset),
        )

    async def get_device(self, workspace_id: str, device_id: str) -> dict[str, Any]:
        """GET /workspaces/{workspaceID}/devices/{deviceID}"""
        return await self._get(f"/workspaces/{workspace_id}/devices/{device_id}")

    async def update_device_name(
        self, workspace_id: str, device_id: str, name: str
    ) -> dict[str, Any]:
        """PUT /workspaces/{workspaceID}/devices/{deviceID}"""
        return await self._put(
            f"/workspaces/{workspace_id}/devices/{device_id}",
            json_body={"name": name},
        )

    async def list_device_clients(
        self, workspace_id: str, device_id: str, limit: int = 200, offset: int = 0
    ) -> dict[str, Any]:
        """GET /workspaces/{workspaceID}/devices/{deviceID}/clients"""
        return await self._get(
            f"/workspaces/{workspace_id}/devices/{device_id}/clients",
            params=self._page_params(limit, offset),
        )

    async def update_device_network(
        self, workspace_id: str, device_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """PUT /workspaces/{workspaceID}/devices/{deviceID}/network"""
        return await self._put(
            f"/workspaces/{workspace_id}/devices/{device_id}/network",
            json_body=data,
        )

    async def update_device_wireless(
        self, workspace_id: str, device_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """PUT /workspaces/{workspaceID}/devices/{deviceID}/wireless"""
        return await self._put(
            f"/workspaces/{workspace_id}/devices/{device_id}/wireless",
            json_body=data,
        )
