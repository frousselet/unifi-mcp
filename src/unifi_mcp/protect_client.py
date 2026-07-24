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
    """Async client for the UniFi Protect integration API.

    Two connection modes are supported:

    - **Local console**: set ``UNIFI_PROTECT_HOST`` (or pass ``host``). Requests
      go to ``https://<host>/proxy/protect/integration/v1/…`` with the local
      console's self-signed certificate.
    - **Cloud connector**: set ``UNIFI_PROTECT_CONSOLE_ID`` / ``UNIFI_CONSOLE_ID``
      (or pass ``console_id``). Requests are proxied through
      ``https://api.ui.com/v1/connector/consoles/<id>/proxy/protect/integration/v1/…``
      using a cloud API key created at unifi.ui.com. No local host needed.

    Local mode takes precedence when both are configured.
    """

    CLOUD_BASE = "https://api.ui.com"

    @staticmethod
    def is_configured() -> bool:
        """Whether the environment enables the Protect client (host or console id)."""
        return bool(
            os.environ.get("UNIFI_PROTECT_HOST")
            or os.environ.get("UNIFI_PROTECT_CONSOLE_ID")
            or os.environ.get("UNIFI_CONSOLE_ID")
        )

    def __init__(
        self,
        host: str | None = None,
        console_id: str | None = None,
        api_key: str | None = None,
        verify_ssl: bool | None = None,
        timeout: float | None = None,
    ):
        self.host = host or os.environ.get("UNIFI_PROTECT_HOST", "")
        self.console_id = (
            console_id
            or os.environ.get("UNIFI_PROTECT_CONSOLE_ID", "")
            or os.environ.get("UNIFI_CONSOLE_ID", "")
        )
        if not self.host and not self.console_id:
            raise ValueError(
                "UniFi Protect requires either a local host or a cloud console ID. "
                "Set UNIFI_PROTECT_HOST for a local console, or UNIFI_CONSOLE_ID "
                "(with a cloud API key) to reach it through api.ui.com."
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
        resolved_timeout = timeout or float(
            os.environ.get("UNIFI_API_TIMEOUT", "30")
        )

        if self.host:
            base_url = f"https://{self.host}/proxy/protect/integration"
            if verify_ssl is None:
                verify_ssl = (
                    os.environ.get("UNIFI_PROTECT_VERIFY_SSL", "false").lower()
                    == "true"
                )
        else:
            base_url = (
                f"{self.CLOUD_BASE}/v1/connector/consoles/"
                f"{self.console_id}/proxy/protect/integration"
            )
            verify_ssl = True

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

    async def get_camera_snapshot(
        self,
        camera_id: str,
        channel: str | None = None,
        high_quality: bool | None = None,
    ) -> bytes:
        """GET /v1/cameras/{id}/snapshot — returns JPEG bytes.

        channel: "main" (default) or "package" for package-camera devices.
        high_quality: force 1080P or higher resolution.
        """
        params: dict[str, Any] = {}
        if channel:
            params["channel"] = channel
        if high_quality is not None:
            params["highQuality"] = "true" if high_quality else "false"
        return await self._get_raw(
            f"/v1/cameras/{camera_id}/snapshot", params=params or None
        )

    async def disable_camera_mic(self, camera_id: str) -> Any:
        """POST /v1/cameras/{id}/disable-mic-permanently"""
        return await self._post(f"/v1/cameras/{camera_id}/disable-mic-permanently")

    # --- Camera RTSPS streams & talkback ---

    async def get_camera_rtsps_streams(self, camera_id: str) -> Any:
        return await self._get(f"/v1/cameras/{camera_id}/rtsps-stream")

    async def create_camera_rtsps_streams(
        self, camera_id: str, qualities: list[str]
    ) -> Any:
        return await self._post(
            f"/v1/cameras/{camera_id}/rtsps-stream",
            json_body={"qualities": qualities},
        )

    async def delete_camera_rtsps_streams(
        self, camera_id: str, qualities: list[str]
    ) -> Any:
        return await self._delete(
            f"/v1/cameras/{camera_id}/rtsps-stream",
            params={"qualities": qualities},
        )

    async def create_camera_talkback_session(self, camera_id: str) -> Any:
        return await self._post(f"/v1/cameras/{camera_id}/talkback-session")

    # --- Camera PTZ control ---

    async def ptz_goto_preset(self, camera_id: str, slot: str) -> Any:
        """POST /v1/cameras/{id}/ptz/goto/{slot} — slot -1 is home preset."""
        return await self._post(f"/v1/cameras/{camera_id}/ptz/goto/{slot}")

    async def ptz_start_patrol(self, camera_id: str, slot: str) -> Any:
        """POST /v1/cameras/{id}/ptz/patrol/start/{slot}"""
        return await self._post(f"/v1/cameras/{camera_id}/ptz/patrol/start/{slot}")

    async def ptz_stop_patrol(self, camera_id: str) -> Any:
        """POST /v1/cameras/{id}/ptz/patrol/stop"""
        return await self._post(f"/v1/cameras/{camera_id}/ptz/patrol/stop")

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

    # --- Sirens ---

    async def list_sirens(self) -> Any:
        return await self._get("/v1/sirens")

    async def get_siren(self, siren_id: str) -> Any:
        return await self._get(f"/v1/sirens/{siren_id}")

    async def update_siren(self, siren_id: str, data: dict[str, Any]) -> Any:
        return await self._patch(f"/v1/sirens/{siren_id}", json_body=data)

    async def play_siren(
        self, siren_id: str, duration: int | None = None
    ) -> Any:
        body = {"duration": duration} if duration is not None else None
        return await self._post(f"/v1/sirens/{siren_id}/play", json_body=body)

    async def stop_siren(self, siren_id: str) -> Any:
        return await self._post(f"/v1/sirens/{siren_id}/stop")

    async def test_siren_sound(
        self, siren_id: str, volume: int | None = None
    ) -> Any:
        body = {"volume": volume} if volume is not None else None
        return await self._post(f"/v1/sirens/{siren_id}/test-sound", json_body=body)

    # --- Speakers ---

    async def list_speakers(self) -> Any:
        return await self._get("/v1/speakers")

    async def get_speaker(self, speaker_id: str) -> Any:
        return await self._get(f"/v1/speakers/{speaker_id}")

    async def update_speaker(self, speaker_id: str, data: dict[str, Any]) -> Any:
        return await self._patch(f"/v1/speakers/{speaker_id}", json_body=data)

    async def test_speaker_sound(
        self, speaker_id: str, volume: int | None = None
    ) -> Any:
        body = {"volume": volume} if volume is not None else None
        return await self._post(
            f"/v1/speakers/{speaker_id}/test-sound", json_body=body
        )

    # --- Fobs ---

    async def list_fobs(self) -> Any:
        return await self._get("/v1/fobs")

    async def get_fob(self, fob_id: str) -> Any:
        return await self._get(f"/v1/fobs/{fob_id}")

    async def update_fob(self, fob_id: str, data: dict[str, Any]) -> Any:
        return await self._patch(f"/v1/fobs/{fob_id}", json_body=data)

    # --- Relays ---

    async def list_relays(self) -> Any:
        return await self._get("/v1/relays")

    async def get_relay(self, relay_id: str) -> Any:
        return await self._get(f"/v1/relays/{relay_id}")

    async def update_relay(self, relay_id: str, data: dict[str, Any]) -> Any:
        return await self._patch(f"/v1/relays/{relay_id}", json_body=data)

    async def activate_relay_output(
        self, relay_id: str, output_id: int, data: dict[str, Any] | None = None
    ) -> Any:
        """POST /v1/relays/{id}/outputs/{outputId}/activate"""
        return await self._post(
            f"/v1/relays/{relay_id}/outputs/{output_id}/activate",
            json_body=data,
        )

    # --- Bridges ---

    async def list_bridges(self) -> Any:
        return await self._get("/v1/bridges")

    async def get_bridge(self, bridge_id: str) -> Any:
        return await self._get(f"/v1/bridges/{bridge_id}")

    async def update_bridge(self, bridge_id: str, data: dict[str, Any]) -> Any:
        return await self._patch(f"/v1/bridges/{bridge_id}", json_body=data)

    # --- Link Stations ---

    async def list_link_stations(self) -> Any:
        return await self._get("/v1/link-stations")

    async def get_link_station(self, link_station_id: str) -> Any:
        return await self._get(f"/v1/link-stations/{link_station_id}")

    async def update_link_station(
        self, link_station_id: str, data: dict[str, Any]
    ) -> Any:
        return await self._patch(
            f"/v1/link-stations/{link_station_id}", json_body=data
        )

    # --- Alarm Hubs ---

    async def list_alarm_hubs(self) -> Any:
        return await self._get("/v1/alarm-hubs")

    async def get_alarm_hub(self, alarm_hub_id: str) -> Any:
        return await self._get(f"/v1/alarm-hubs/{alarm_hub_id}")

    async def update_alarm_hub(
        self, alarm_hub_id: str, data: dict[str, Any]
    ) -> Any:
        return await self._patch(
            f"/v1/alarm-hubs/{alarm_hub_id}", json_body=data
        )

    async def trigger_alarm_hub_output(
        self, alarm_hub_id: str, output_id: int, data: dict[str, Any] | None = None
    ) -> Any:
        """POST /v1/alarm-hubs/{id}/outputs/{outputId}/trigger"""
        return await self._post(
            f"/v1/alarm-hubs/{alarm_hub_id}/outputs/{output_id}/trigger",
            json_body=data,
        )

    # --- Arm Profiles (local alarm manager) ---

    async def list_arm_profiles(self) -> Any:
        return await self._get("/v1/arm-profiles")

    async def create_arm_profile(self, data: dict[str, Any]) -> Any:
        return await self._post("/v1/arm-profiles", json_body=data)

    async def update_arm_profile(
        self, arm_profile_id: str, data: dict[str, Any]
    ) -> Any:
        return await self._patch(
            f"/v1/arm-profiles/{arm_profile_id}", json_body=data
        )

    async def delete_arm_profile(self, arm_profile_id: str) -> Any:
        return await self._delete(f"/v1/arm-profiles/{arm_profile_id}")

    async def set_current_arm_profile(self, arm_profile_id: str) -> Any:
        """PATCH /v1/arm-profiles/settings"""
        return await self._patch(
            "/v1/arm-profiles/settings",
            json_body={"armProfileId": arm_profile_id},
        )

    async def enable_arm_alarm(self) -> Any:
        return await self._post("/v1/arm-profiles/enable")

    async def disable_arm_alarm(self) -> Any:
        return await self._post("/v1/arm-profiles/disable")

    # --- Alarm Manager webhook ---

    async def send_alarm_webhook(self, trigger_id: str) -> Any:
        """POST /v1/alarm-manager/webhook/{id}"""
        return await self._post(f"/v1/alarm-manager/webhook/{trigger_id}")

    # --- Users & Identity Users ---

    async def list_users(self) -> Any:
        return await self._get("/v1/users")

    async def get_user(self, user_id: str) -> Any:
        return await self._get(f"/v1/users/{user_id}")

    async def list_ulp_users(self) -> Any:
        return await self._get("/v1/ulp-users")

    async def get_ulp_user(self, ulp_user_id: str) -> Any:
        return await self._get(f"/v1/ulp-users/{ulp_user_id}")

    # --- Device asset files ---

    async def list_files(self, file_type: str = "animations") -> Any:
        return await self._get(f"/v1/files/{file_type}")
