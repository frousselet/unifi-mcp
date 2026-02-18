"""UniFi Protect API client (local console)."""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ProtectApiError(Exception):
    """Raised when the UniFi Protect API returns an error."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"UniFi Protect API error {status_code}: {message}")


class ProtectClient:
    """Async client for the UniFi Protect API (local console).

    Connects to a UniFi console (UDM, UNVR, etc.) via its local API
    at https://<host>/proxy/protect/api/v1/.
    """

    def __init__(
        self,
        host: str | None = None,
        api_key: str | None = None,
        verify_ssl: bool | None = None,
        timeout: float | None = None,
    ):
        self.host = host or os.environ.get("UNIFI_PROTECT_HOST", "")
        if not self.host:
            raise ValueError(
                "UniFi Protect host is required. Set UNIFI_PROTECT_HOST "
                "environment variable or pass host parameter."
            )
        self.api_key = (
            api_key
            or os.environ.get("UNIFI_PROTECT_API_KEY", "")
            or os.environ.get("UNIFI_API_KEY", "")
        )
        if not self.api_key:
            raise ValueError(
                "UniFi API key is required. Set UNIFI_PROTECT_API_KEY "
                "or UNIFI_API_KEY environment variable, or pass api_key parameter."
            )
        if verify_ssl is None:
            verify_ssl = (
                os.environ.get("UNIFI_PROTECT_VERIFY_SSL", "false").lower() == "true"
            )
        resolved_timeout = timeout or float(
            os.environ.get("UNIFI_API_TIMEOUT", "30")
        )

        base_url = f"https://{self.host}/proxy/protect/api"
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "X-API-KEY": self.api_key,
                "Accept": "application/json",
            },
            verify=verify_ssl,
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
    ) -> Any:
        """Make an authenticated request to the Protect API.

        Unlike the Network API, many Protect endpoints return JSON arrays
        directly (not wrapped in {"data": [...]}).
        """
        response = await self._client.request(
            method, path, params=params, json=json_body
        )

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            raise ProtectApiError(
                429, f"Rate limited. Retry after {retry_after} seconds."
            )

        if response.status_code == 204:
            return {"status": "success"}

        data = response.json()

        if response.status_code >= 400:
            if isinstance(data, dict):
                message = (
                    data.get("message", "")
                    or data.get("error", "")
                    or response.text
                )
            else:
                message = response.text
            raise ProtectApiError(response.status_code, message)

        return data

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        return await self._request("GET", path, params=params)

    async def _post(
        self, path: str, json_body: dict[str, Any] | None = None
    ) -> Any:
        return await self._request("POST", path, json_body=json_body)

    async def _patch(
        self, path: str, json_body: dict[str, Any] | None = None
    ) -> Any:
        return await self._request("PATCH", path, json_body=json_body)

    async def _delete(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        return await self._request("DELETE", path, params=params)

    async def _get_raw(
        self, path: str, params: dict[str, Any] | None = None
    ) -> bytes:
        """GET request that returns raw bytes (for snapshots)."""
        response = await self._client.request("GET", path, params=params)

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            raise ProtectApiError(
                429, f"Rate limited. Retry after {retry_after} seconds."
            )

        if response.status_code >= 400:
            raise ProtectApiError(response.status_code, response.text)

        return response.content

    # --- App Info ---

    async def get_app_info(self) -> dict[str, Any]:
        """GET /v1/meta/info"""
        return await self._get("/v1/meta/info")

    # --- NVR ---

    async def get_nvr(self) -> Any:
        """GET /v1/nvrs"""
        return await self._get("/v1/nvrs")

    # --- Cameras ---

    async def list_cameras(self) -> Any:
        return await self._get("/v1/cameras")

    async def get_camera(self, camera_id: str) -> Any:
        return await self._get(f"/v1/cameras/{camera_id}")

    async def update_camera(
        self, camera_id: str, data: dict[str, Any]
    ) -> Any:
        return await self._patch(f"/v1/cameras/{camera_id}", json_body=data)

    async def get_camera_snapshot(self, camera_id: str) -> bytes:
        """GET /v1/cameras/{id}/snapshot — returns JPEG bytes."""
        return await self._get_raw(f"/v1/cameras/{camera_id}/snapshot")

    # --- Lights ---

    async def list_lights(self) -> Any:
        return await self._get("/v1/lights")

    async def get_light(self, light_id: str) -> Any:
        return await self._get(f"/v1/lights/{light_id}")

    async def update_light(
        self, light_id: str, data: dict[str, Any]
    ) -> Any:
        return await self._patch(f"/v1/lights/{light_id}", json_body=data)

    # --- Sensors ---

    async def list_sensors(self) -> Any:
        return await self._get("/v1/sensors")

    async def get_sensor(self, sensor_id: str) -> Any:
        return await self._get(f"/v1/sensors/{sensor_id}")

    async def update_sensor(
        self, sensor_id: str, data: dict[str, Any]
    ) -> Any:
        return await self._patch(f"/v1/sensors/{sensor_id}", json_body=data)

    # --- Chimes ---

    async def list_chimes(self) -> Any:
        return await self._get("/v1/chimes")

    async def get_chime(self, chime_id: str) -> Any:
        return await self._get(f"/v1/chimes/{chime_id}")

    async def update_chime(
        self, chime_id: str, data: dict[str, Any]
    ) -> Any:
        return await self._patch(f"/v1/chimes/{chime_id}", json_body=data)

    # --- Door Locks ---

    async def list_doorlocks(self) -> Any:
        return await self._get("/v1/doorlocks")

    async def get_doorlock(self, doorlock_id: str) -> Any:
        return await self._get(f"/v1/doorlocks/{doorlock_id}")

    async def update_doorlock(
        self, doorlock_id: str, data: dict[str, Any]
    ) -> Any:
        return await self._patch(
            f"/v1/doorlocks/{doorlock_id}", json_body=data
        )

    # --- Events ---

    async def list_events(self) -> Any:
        """GET /v1/events — returns up to 10K events."""
        return await self._get("/v1/events")

    # --- Liveviews ---

    async def list_liveviews(self) -> Any:
        return await self._get("/v1/liveviews")

    async def get_liveview(self, liveview_id: str) -> Any:
        return await self._get(f"/v1/liveviews/{liveview_id}")

    async def create_liveview(self, data: dict[str, Any]) -> Any:
        return await self._post("/v1/liveviews", json_body=data)

    async def update_liveview(
        self, liveview_id: str, data: dict[str, Any]
    ) -> Any:
        return await self._patch(
            f"/v1/liveviews/{liveview_id}", json_body=data
        )

    # --- Viewers ---

    async def list_viewers(self) -> Any:
        return await self._get("/v1/viewers")

    async def get_viewer(self, viewer_id: str) -> Any:
        return await self._get(f"/v1/viewers/{viewer_id}")

    async def update_viewer(
        self, viewer_id: str, data: dict[str, Any]
    ) -> Any:
        return await self._patch(f"/v1/viewers/{viewer_id}", json_body=data)
