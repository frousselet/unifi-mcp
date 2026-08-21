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
    """Async client for the UniFi Network integration API.

    Two connection modes are supported:

    - **Local console**: set ``UNIFI_NETWORK_HOST`` (or pass ``host``). Requests
      go to ``https://<host>/proxy/network/integration/v1/…`` with the local
      console's self-signed certificate.
    - **Cloud connector**: set ``UNIFI_NETWORK_CONSOLE_ID`` / ``UNIFI_CONSOLE_ID``
      (or pass ``console_id``). Requests are proxied through
      ``https://api.ui.com/v1/connector/consoles/<id>/proxy/network/integration/v1/…``
      using a cloud API key created at unifi.ui.com. No local host needed.

    Local mode takes precedence when both are configured.
    """

    CLOUD_BASE = "https://api.ui.com"

    @staticmethod
    def is_configured() -> bool:
        """Whether the environment enables the Network client (host or console id)."""
        return bool(
            os.environ.get("UNIFI_NETWORK_HOST")
            or os.environ.get("UNIFI_NETWORK_CONSOLE_ID")
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
        self.host = host or os.environ.get("UNIFI_NETWORK_HOST", "")
        self.console_id = (
            console_id
            or os.environ.get("UNIFI_NETWORK_CONSOLE_ID", "")
            or os.environ.get("UNIFI_CONSOLE_ID", "")
        )
        if not self.host and not self.console_id:
            raise ValueError(
                "UniFi Network requires either a local host or a cloud console ID. "
                "Set UNIFI_NETWORK_HOST for a local console, or UNIFI_CONSOLE_ID "
                "(with a cloud API key) to reach it through api.ui.com."
            )
        self.api_key = (
            api_key
            or os.environ.get("UNIFI_NETWORK_API_KEY", "")
            or os.environ.get("UNIFI_API_KEY", "")
        )
        if not self.api_key:
            raise ValueError(
                "UniFi API key is required. Set UNIFI_NETWORK_API_KEY "
                "or UNIFI_API_KEY environment variable, or pass api_key parameter."
            )
        resolved_timeout = timeout or float(os.environ.get("UNIFI_API_TIMEOUT", "30"))

        if self.host:
            base_url = f"https://{self.host}/proxy/network/integration"
            if verify_ssl is None:
                verify_ssl = (
                    os.environ.get("UNIFI_NETWORK_VERIFY_SSL", "false").lower()
                    == "true"
                )
        else:
            base_url = (
                f"{self.CLOUD_BASE}/v1/connector/consoles/"
                f"{self.console_id}/proxy/network/integration"
            )
            # api.ui.com has a valid public certificate.
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

    # --- Pending devices & adoption ---

    async def list_pending_devices(
        self, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            "/v1/pending-devices",
            params=self._pagination_params(offset, limit),
        )

    async def adopt_device(
        self, site_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._post(f"/v1/sites/{site_id}/devices", json_body=data)

    async def remove_device(
        self, site_id: str, device_id: str
    ) -> dict[str, Any]:
        return await self._delete(f"/v1/sites/{site_id}/devices/{device_id}")

    async def execute_port_action(
        self, site_id: str, device_id: str, port_idx: int, action: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._post(
            f"/v1/sites/{site_id}/devices/{device_id}/interfaces/ports/{port_idx}/actions",
            json_body=action,
        )

    # --- Network references ---

    async def get_network_references(
        self, site_id: str, network_id: str
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/networks/{network_id}/references"
        )

    # --- ACL rules ---

    async def list_acl_rules(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/acl-rules",
            params=self._pagination_params(offset, limit),
        )

    async def get_acl_rule(self, site_id: str, acl_rule_id: str) -> dict[str, Any]:
        return await self._get(f"/v1/sites/{site_id}/acl-rules/{acl_rule_id}")

    async def create_acl_rule(
        self, site_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._post(f"/v1/sites/{site_id}/acl-rules", json_body=data)

    async def update_acl_rule(
        self, site_id: str, acl_rule_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._put(
            f"/v1/sites/{site_id}/acl-rules/{acl_rule_id}", json_body=data
        )

    async def delete_acl_rule(
        self, site_id: str, acl_rule_id: str
    ) -> dict[str, Any]:
        return await self._delete(f"/v1/sites/{site_id}/acl-rules/{acl_rule_id}")

    async def get_acl_rule_ordering(self, site_id: str) -> dict[str, Any]:
        return await self._get(f"/v1/sites/{site_id}/acl-rules/ordering")

    async def update_acl_rule_ordering(
        self, site_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._put(
            f"/v1/sites/{site_id}/acl-rules/ordering", json_body=data
        )

    # --- DNS policy CRUD (list defined above) ---

    async def get_dns_policy(
        self, site_id: str, dns_policy_id: str
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/dns/policies/{dns_policy_id}"
        )

    async def create_dns_policy(
        self, site_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._post(
            f"/v1/sites/{site_id}/dns/policies", json_body=data
        )

    async def update_dns_policy(
        self, site_id: str, dns_policy_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._put(
            f"/v1/sites/{site_id}/dns/policies/{dns_policy_id}", json_body=data
        )

    async def delete_dns_policy(
        self, site_id: str, dns_policy_id: str
    ) -> dict[str, Any]:
        return await self._delete(
            f"/v1/sites/{site_id}/dns/policies/{dns_policy_id}"
        )

    # --- Firewall zones CRUD & policy ordering ---

    async def get_firewall_zone(
        self, site_id: str, firewall_zone_id: str
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/firewall/zones/{firewall_zone_id}"
        )

    async def create_firewall_zone(
        self, site_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._post(
            f"/v1/sites/{site_id}/firewall/zones", json_body=data
        )

    async def update_firewall_zone(
        self, site_id: str, firewall_zone_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._put(
            f"/v1/sites/{site_id}/firewall/zones/{firewall_zone_id}", json_body=data
        )

    async def delete_firewall_zone(
        self, site_id: str, firewall_zone_id: str
    ) -> dict[str, Any]:
        return await self._delete(
            f"/v1/sites/{site_id}/firewall/zones/{firewall_zone_id}"
        )

    async def get_firewall_policy(
        self, site_id: str, policy_id: str
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/firewall/policies/{policy_id}"
        )

    async def get_firewall_policy_ordering(
        self, site_id: str, source_zone_id: str, destination_zone_id: str
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/firewall/policies/ordering",
            params={
                "sourceFirewallZoneId": source_zone_id,
                "destinationFirewallZoneId": destination_zone_id,
            },
        )

    async def update_firewall_policy_ordering(
        self,
        site_id: str,
        source_zone_id: str,
        destination_zone_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._put(
            f"/v1/sites/{site_id}/firewall/policies/ordering?"
            f"sourceFirewallZoneId={source_zone_id}&"
            f"destinationFirewallZoneId={destination_zone_id}",
            json_body=data,
        )

    # --- Traffic matching lists ---

    async def list_traffic_matching_lists(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/traffic-matching-lists",
            params=self._pagination_params(offset, limit),
        )

    async def get_traffic_matching_list(
        self, site_id: str, list_id: str
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/traffic-matching-lists/{list_id}"
        )

    async def create_traffic_matching_list(
        self, site_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._post(
            f"/v1/sites/{site_id}/traffic-matching-lists", json_body=data
        )

    async def update_traffic_matching_list(
        self, site_id: str, list_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._put(
            f"/v1/sites/{site_id}/traffic-matching-lists/{list_id}", json_body=data
        )

    async def delete_traffic_matching_list(
        self, site_id: str, list_id: str
    ) -> dict[str, Any]:
        return await self._delete(
            f"/v1/sites/{site_id}/traffic-matching-lists/{list_id}"
        )

    # --- Switching (LAGs, MC-LAG domains, switch stacks) ---

    async def list_lags(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/switching/lags",
            params=self._pagination_params(offset, limit),
        )

    async def get_lag(self, site_id: str, lag_id: str) -> dict[str, Any]:
        return await self._get(f"/v1/sites/{site_id}/switching/lags/{lag_id}")

    async def list_mc_lag_domains(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/switching/mc-lag-domains",
            params=self._pagination_params(offset, limit),
        )

    async def get_mc_lag_domain(
        self, site_id: str, mc_lag_domain_id: str
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/switching/mc-lag-domains/{mc_lag_domain_id}"
        )

    async def list_switch_stacks(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/switching/switch-stacks",
            params=self._pagination_params(offset, limit),
        )

    async def get_switch_stack(
        self, site_id: str, switch_stack_id: str
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/switching/switch-stacks/{switch_stack_id}"
        )

    # --- Supporting resources (site-scoped & global) ---

    async def list_device_tags(
        self, site_id: str, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            f"/v1/sites/{site_id}/device-tags",
            params=self._pagination_params(offset, limit),
        )

    async def list_countries(
        self, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            "/v1/countries", params=self._pagination_params(offset, limit)
        )

    async def list_dpi_applications(
        self, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            "/v1/dpi/applications", params=self._pagination_params(offset, limit)
        )

    async def list_dpi_categories(
        self, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        return await self._get(
            "/v1/dpi/categories", params=self._pagination_params(offset, limit)
        )
