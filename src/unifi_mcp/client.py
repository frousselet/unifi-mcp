"""UniFi Site Manager API client."""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

UNIFI_API_BASE_URL = "https://api.ui.com/v1"


class UniFiApiError(Exception):
    """Raised when the UniFi API returns an error."""

    def __init__(self, status_code: int, message: str, trace_id: str | None = None):
        self.status_code = status_code
        self.message = message
        self.trace_id = trace_id
        super().__init__(f"UniFi API error {status_code}: {message}")


class UniFiClient:
    """Async client for the UniFi Site Manager API (v1).

    Handles authentication, pagination, rate-limit awareness, and error mapping.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ):
        self.api_key = api_key or os.environ.get("UNIFI_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "UniFi API key is required. Set UNIFI_API_KEY environment variable "
                "or pass api_key parameter."
            )
        resolved_base_url = (
            base_url
            or os.environ.get("UNIFI_API_BASE_URL")
            or UNIFI_API_BASE_URL
        )
        resolved_timeout = (
            timeout
            or float(os.environ.get("UNIFI_API_TIMEOUT", "30"))
        )
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
        """Make an authenticated request to the UniFi API."""
        response = await self._client.request(
            method, path, params=params, json=json_body
        )

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            raise UniFiApiError(
                429,
                f"Rate limited. Retry after {retry_after} seconds.",
            )

        data = response.json()
        trace_id = data.get("traceId")

        if response.status_code >= 400:
            raise UniFiApiError(
                response.status_code,
                data.get("message", response.text),
                trace_id=trace_id,
            )

        return data

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def _post(
        self,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._request("POST", path, params=params, json_body=json_body)

    # --- Hosts ---

    async def list_hosts(
        self, page_size: int = 25, next_token: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": str(page_size)}
        if next_token:
            params["nextToken"] = next_token
        return await self._get("/hosts", params=params)

    async def get_host(self, host_id: str) -> dict[str, Any]:
        return await self._get(f"/hosts/{host_id}")

    # --- Sites ---

    async def list_sites(
        self, page_size: int = 25, next_token: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": str(page_size)}
        if next_token:
            params["nextToken"] = next_token
        return await self._get("/sites", params=params)

    # --- Devices ---

    async def list_devices(
        self,
        host_ids: list[str] | None = None,
        time: str | None = None,
        page_size: int = 25,
        next_token: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"pageSize": str(page_size)}
        if next_token:
            params["nextToken"] = next_token
        if host_ids:
            params["hostIds[]"] = host_ids
        if time:
            params["time"] = time
        return await self._get("/devices", params=params)

    # --- ISP Metrics ---

    async def get_isp_metrics(
        self,
        metric_type: str,
        duration: str | None = None,
        begin_timestamp: str | None = None,
        end_timestamp: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if duration:
            params["duration"] = duration
        if begin_timestamp:
            params["beginTimestamp"] = begin_timestamp
        if end_timestamp:
            params["endTimestamp"] = end_timestamp
        return await self._get(f"/isp-metrics/{metric_type}", params=params)

    async def query_isp_metrics(
        self,
        metric_type: str,
        sites: list[dict[str, str]],
        begin_timestamp: str | None = None,
        end_timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Query ISP metrics for specific sites.

        Args:
            metric_type: "5m" or "1h".
            sites: List of dicts with "hostId" and "siteId" keys,
                   optionally "beginTimestamp" and "endTimestamp".
        """
        return await self._post(
            f"/isp-metrics/{metric_type}/query",
            json_body={"sites": sites},
        )

    # --- SD-WAN ---

    async def list_sdwan_configs(self) -> dict[str, Any]:
        return await self._get("/sd-wan-configs")

    async def get_sdwan_config(self, config_id: str) -> dict[str, Any]:
        return await self._get(f"/sd-wan-configs/{config_id}")

    async def get_sdwan_config_status(self, config_id: str) -> dict[str, Any]:
        return await self._get(f"/sd-wan-configs/{config_id}/status")
