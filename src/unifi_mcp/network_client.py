"""UniFi Network API client (local console)."""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class NetworkApiError(Exception):
    """Raised when the UniFi Network API returns an error."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"UniFi Network API error {status_code}: {message}")


class NetworkClient:
    """Async client for the UniFi Network API (local console).

    Connects to a UniFi console (UDM, UCG, etc.) via its local API
    at https://<host>/proxy/network/integration/v1/.
    """

    def __init__(
        self,
        host: str | None = None,
        api_key: str | None = None,
        verify_ssl: bool | None = None,
        timeout: float | None = None,
    ):
        self.host = host or os.environ.get("UNIFI_NETWORK_HOST", "")
        if not self.host:
            raise ValueError(
                "UniFi Network host is required. Set UNIFI_NETWORK_HOST "
                "environment variable or pass host parameter."
            )
        self.api_key = api_key or os.environ.get("UNIFI_NETWORK_API_KEY", "") or os.environ.get("UNIFI_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "UniFi API key is required. Set UNIFI_NETWORK_API_KEY "
                "or UNIFI_API_KEY environment variable, or pass api_key parameter."
            )
        if verify_ssl is None:
            verify_ssl = os.environ.get("UNIFI_NETWORK_VERIFY_SSL", "false").lower() == "true"
        resolved_timeout = timeout or float(os.environ.get("UNIFI_API_TIMEOUT", "30"))

        base_url = f"https://{self.host}/proxy/network/integration"
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
    ) -> dict[str, Any]:
        """Make an authenticated request to the Network API."""
        response = await self._client.request(
            method, path, params=params, json=json_body
        )

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            raise NetworkApiError(
                429, f"Rate limited. Retry after {retry_after} seconds."
            )

        if response.status_code == 204:
            return {"status": "success"}

        data = response.json()

        if response.status_code >= 400:
            message = data.get("message", "") or data.get("error", "") or response.text
            raise NetworkApiError(response.status_code, message)

        return data

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def _post(
        self, path: str, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request("POST", path, json_body=json_body)

    async def _put(
        self, path: str, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request("PUT", path, json_body=json_body)

    async def _delete(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request("DELETE", path, params=params)

    def _pagination_params(
        self, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return {"offset": offset, "limit": limit}

    # --- Info ---

    async def get_info(self) -> dict[str, Any]:
        return await self._get("/v1/info")

    # --- Sites ---

    async def list_sites(
        self, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get("/v1/sites", params=self._pagination_params(offset, limit))

    # --- Devices ---

    async def list_devices(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/devices",
            params=self._pagination_params(offset, limit),
        )

    async def get_device(self, site_id: str, device_id: str) -> dict[str, Any]:
        return await self._get(f"/v1/sites/{site_id}/devices/{device_id}")

    async def get_device_statistics(
        self, site_id: str, device_id: str
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/devices/{device_id}/statistics/latest"
        )

    async def execute_device_action(
        self, site_id: str, device_id: str, action: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._post(
            f"/v1/sites/{site_id}/devices/{device_id}/actions",
            json_body=action,
        )

    # --- Clients ---

    async def list_clients(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/clients",
            params=self._pagination_params(offset, limit),
        )

    async def get_client(self, site_id: str, client_id: str) -> dict[str, Any]:
        return await self._get(f"/v1/sites/{site_id}/clients/{client_id}")

    async def execute_client_action(
        self, site_id: str, client_id: str, action: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._post(
            f"/v1/sites/{site_id}/clients/{client_id}/actions",
            json_body=action,
        )

    # --- Networks ---

    async def list_networks(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/networks",
            params=self._pagination_params(offset, limit),
        )

    async def get_network(self, site_id: str, network_id: str) -> dict[str, Any]:
        return await self._get(f"/v1/sites/{site_id}/networks/{network_id}")

    async def create_network(
        self, site_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._post(f"/v1/sites/{site_id}/networks", json_body=data)

    async def update_network(
        self, site_id: str, network_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._put(
            f"/v1/sites/{site_id}/networks/{network_id}", json_body=data
        )

    async def delete_network(self, site_id: str, network_id: str) -> dict[str, Any]:
        return await self._delete(f"/v1/sites/{site_id}/networks/{network_id}")

    # --- WiFi ---

    async def list_wifi(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/wifi/broadcasts",
            params=self._pagination_params(offset, limit),
        )

    async def get_wifi(self, site_id: str, wifi_id: str) -> dict[str, Any]:
        return await self._get(f"/v1/sites/{site_id}/wifi/broadcasts/{wifi_id}")

    async def create_wifi(
        self, site_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._post(f"/v1/sites/{site_id}/wifi/broadcasts", json_body=data)

    async def update_wifi(
        self, site_id: str, wifi_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._put(
            f"/v1/sites/{site_id}/wifi/broadcasts/{wifi_id}", json_body=data
        )

    async def delete_wifi(self, site_id: str, wifi_id: str) -> dict[str, Any]:
        return await self._delete(f"/v1/sites/{site_id}/wifi/broadcasts/{wifi_id}")

    # --- Firewall ---

    async def list_firewall_zones(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/firewall/zones",
            params=self._pagination_params(offset, limit),
        )

    async def list_firewall_policies(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/firewall/policies",
            params=self._pagination_params(offset, limit),
        )

    async def create_firewall_policy(
        self, site_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._post(
            f"/v1/sites/{site_id}/firewall/policies", json_body=data
        )

    async def update_firewall_policy(
        self, site_id: str, policy_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._put(
            f"/v1/sites/{site_id}/firewall/policies/{policy_id}", json_body=data
        )

    async def delete_firewall_policy(
        self, site_id: str, policy_id: str
    ) -> dict[str, Any]:
        return await self._delete(
            f"/v1/sites/{site_id}/firewall/policies/{policy_id}"
        )

    # --- DNS ---

    async def list_dns_policies(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/dns/policies",
            params=self._pagination_params(offset, limit),
        )

    # --- Hotspot ---

    async def list_vouchers(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/hotspot/vouchers",
            params=self._pagination_params(offset, limit),
        )

    async def create_vouchers(
        self, site_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._post(
            f"/v1/sites/{site_id}/hotspot/vouchers", json_body=data
        )

    async def delete_voucher(
        self, site_id: str, voucher_id: str
    ) -> dict[str, Any]:
        return await self._delete(
            f"/v1/sites/{site_id}/hotspot/vouchers/{voucher_id}"
        )

    # --- Supporting resources ---

    async def list_wans(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/wans",
            params=self._pagination_params(offset, limit),
        )

    async def list_vpn_tunnels(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/vpn/site-to-site-tunnels",
            params=self._pagination_params(offset, limit),
        )

    async def list_vpn_servers(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/vpn/servers",
            params=self._pagination_params(offset, limit),
        )

    async def list_radius_profiles(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/radius/profiles",
            params=self._pagination_params(offset, limit),
        )
