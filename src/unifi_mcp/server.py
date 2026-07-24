"""UniFi MCP Server -- exposes UniFi Site Manager, Network, and Protect APIs as MCP tools."""

import base64
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from unifi_mcp.client import UniFiApiError, UniFiClient
from unifi_mcp.formatting import (
    format_devices,
    format_host_detail,
    format_hosts,
    format_isp_metrics,
    format_sdwan_config_detail,
    format_sdwan_config_status,
    format_sdwan_configs,
    format_sites,
)
from unifi_mcp.mobility_client import MobilityApiError, MobilityClient
from unifi_mcp.mobility_formatting import (
    format_mobility_admins,
    format_mobility_device_clients,
    format_mobility_device_detail,
    format_mobility_devices,
    format_mobility_result,
    format_mobility_workspaces,
)
from unifi_mcp.network_client import NetworkApiError, NetworkClient
from unifi_mcp.network_formatting import (
    format_action_result,
    format_crud_result,
    format_network_acl_rules,
    format_network_clients,
    format_network_client_detail,
    format_network_countries,
    format_network_detail,
    format_network_device_tags,
    format_network_devices,
    format_network_device_detail,
    format_network_device_statistics,
    format_network_dns_policies,
    format_network_dpi,
    format_network_firewall_policies,
    format_network_firewall_zones,
    format_network_info,
    format_network_lags,
    format_network_mc_lag_domains,
    format_network_network_detail,
    format_network_networks,
    format_network_pending_devices,
    format_network_radius_profiles,
    format_network_sites,
    format_network_switch_stacks,
    format_network_traffic_matching_lists,
    format_network_vouchers,
    format_network_vpn_servers,
    format_network_vpn_tunnels,
    format_network_wans,
    format_network_wifi,
    format_network_wifi_detail,
)
from unifi_mcp.protect_client import ProtectApiError, ProtectClient
from unifi_mcp.protect_formatting import (
    format_protect_alarm_hubs,
    format_protect_app_info,
    format_protect_arm_profiles,
    format_protect_bridges,
    format_protect_camera_detail,
    format_protect_cameras,
    format_protect_chime_detail,
    format_protect_chimes,
    format_protect_crud_result,
    format_protect_device_detail,
    format_protect_events,
    format_protect_fobs,
    format_protect_light_detail,
    format_protect_lights,
    format_protect_link_stations,
    format_protect_liveview_detail,
    format_protect_liveviews,
    format_protect_nvr,
    format_protect_relays,
    format_protect_sensor_detail,
    format_protect_sensors,
    format_protect_sirens,
    format_protect_speakers,
    format_protect_users,
    format_protect_viewer_detail,
    format_protect_viewers,
)
from unifi_mcp.tenant import ClientBundle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("unifi-mcp")


# ---------------------------------------------------------------------------
# Deployment mode
# ---------------------------------------------------------------------------
# Single-tenant (default): one set of credentials from environment variables.
# Multi-tenant: set UNIFI_MULTITENANT=1. Each caller authenticates via OAuth and
# the tenant's credentials are resolved per-request from the access token. In
# this mode no UNIFI_API_KEY is required at startup.

_MULTITENANT = os.environ.get("UNIFI_MULTITENANT", "").lower() in ("1", "true", "yes")

# Multi-tenant singletons (created lazily below so single-tenant imports stay light).
STORE = None  # type: ignore[assignment]
REGISTRY = None  # type: ignore[assignment]
OAUTH_PROVIDER = None  # type: ignore[assignment]

INSTRUCTIONS = (
    "This server provides access to UniFi infrastructure via four APIs:\n"
    "1. **Site Manager API** (cloud): list_hosts, get_host, list_sites, list_devices, "
    "get_isp_metrics, query_isp_metrics, get_sdwan_config\n"
    "2. **Mobility API** (cloud): mobility_* tools for UMR mobile routers — "
    "workspaces, admins, devices, clients, and device name/network/wireless updates\n"
    "3. **Network API**: network_* tools for devices, clients, networks, WiFi, "
    "firewall, ACL rules, DNS, switching, vouchers, and more\n"
    "4. **Protect API**: protect_* tools for cameras (incl. PTZ, RTSPS, snapshots), "
    "lights, sensors, sirens, speakers, relays, alarm hubs, arm profiles, events, "
    "and NVR info\n\n"
    "Start with list_hosts, mobility_list_workspaces, network_info, or protect_info "
    "to discover your infrastructure."
)


@dataclass
class AppContext:
    """Application context holding shared resources (single-tenant only)."""

    bundle: ClientBundle | None


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage API client lifecycles."""
    bundle: ClientBundle | None = None
    if _MULTITENANT:
        logger.info("Multi-tenant mode: credentials resolved per request via OAuth")
    else:
        bundle = ClientBundle.from_config(
            api_key=os.environ.get("UNIFI_API_KEY", ""),
            network_console_id=os.environ.get("UNIFI_NETWORK_CONSOLE_ID")
            or os.environ.get("UNIFI_CONSOLE_ID"),
            protect_console_id=os.environ.get("UNIFI_PROTECT_CONSOLE_ID")
            or os.environ.get("UNIFI_CONSOLE_ID"),
            network_host=os.environ.get("UNIFI_NETWORK_HOST"),
            protect_host=os.environ.get("UNIFI_PROTECT_HOST"),
        )
        logger.info(
            "Single-tenant clients initialized (network=%s, protect=%s)",
            bool(bundle.network),
            bool(bundle.protect),
        )

    try:
        yield AppContext(bundle=bundle)
    finally:
        if bundle is not None:
            await bundle.aclose()
        if REGISTRY is not None:
            await REGISTRY.aclose()
        logger.info("API clients closed")


def _build_mcp() -> FastMCP:
    """Construct the FastMCP server, enabling OAuth auth in multi-tenant mode."""
    kwargs: dict = dict(instructions=INSTRUCTIONS, lifespan=app_lifespan)
    if _MULTITENANT:
        from unifi_mcp.oauth import SCOPE, UniFiOAuthProvider
        from unifi_mcp.tenant import BundleRegistry, TenantStore

        global STORE, REGISTRY, OAUTH_PROVIDER
        STORE = TenantStore()
        REGISTRY = BundleRegistry(STORE)
        OAUTH_PROVIDER = UniFiOAuthProvider(STORE)

        public_url = os.environ.get("UNIFI_PUBLIC_URL", "http://localhost:8000").rstrip(
            "/"
        )
        kwargs["auth_server_provider"] = OAUTH_PROVIDER
        kwargs["auth"] = AuthSettings(
            issuer_url=public_url,  # type: ignore[arg-type]
            resource_server_url=public_url,  # type: ignore[arg-type]
            required_scopes=[SCOPE],
            client_registration_options=ClientRegistrationOptions(enabled=False),
        )
    return FastMCP("unifi", **kwargs)


mcp = _build_mcp()


def _error_response(e: UniFiApiError) -> str:
    parts = [f"Error {e.status_code}: {e.message}"]
    if e.trace_id:
        parts.append(f"Trace ID: {e.trace_id}")
    return "\n".join(parts)


def _network_error_response(e: NetworkApiError) -> str:
    return f"Error {e.status_code}: {e.message}"


def _get_app_context() -> AppContext:
    """Get the AppContext from the MCP lifespan context."""
    return mcp.get_context().request_context.lifespan_context


def _current_bundle() -> ClientBundle:
    """Resolve the client bundle for the current request.

    Multi-tenant: from the authenticated access token's client_id.
    Single-tenant: the process-wide bundle built from environment variables.
    """
    if _MULTITENANT:
        token = get_access_token()
        if token is None:
            raise UniFiApiError(401, "Unauthenticated: missing or invalid access token.")
        bundle = REGISTRY.bundle_for_client_id(token.client_id) if REGISTRY else None
        if bundle is None:
            raise UniFiApiError(403, "Unknown tenant for the presented credentials.")
        return bundle

    bundle = _get_app_context().bundle
    if bundle is None:  # pragma: no cover - defensive
        raise UniFiApiError(500, "Server not configured with credentials.")
    return bundle


def _get_network_client() -> NetworkClient:
    """Get the Network API client for the current request, or raise a clear error."""
    client: NetworkClient | None = _current_bundle().network
    if client is None:
        raise NetworkApiError(
            0,
            "Network API not configured for this tenant. Provide a console ID "
            "(cloud connector via api.ui.com) or set UNIFI_NETWORK_HOST locally.",
        )
    return client


def _mobility_error_response(e: MobilityApiError) -> str:
    parts = [f"Error {e.status_code}: {e.message}"]
    if e.trace_id:
        parts.append(f"Trace ID: {e.trace_id}")
    return "\n".join(parts)


def _get_mobility_client() -> MobilityClient:
    """Get the Mobility API client for the current request."""
    return _current_bundle().mobility


def _protect_error_response(e: ProtectApiError) -> str:
    return f"Error {e.status_code}: {e.message}"


def _get_protect_client() -> ProtectClient:
    """Get the Protect API client for the current request, or raise a clear error."""
    client: ProtectClient | None = _current_bundle().protect
    if client is None:
        raise ProtectApiError(
            0,
            "Protect API not configured for this tenant. Provide a console ID "
            "(cloud connector via api.ui.com) or set UNIFI_PROTECT_HOST locally.",
        )
    return client


# ---------------------------------------------------------------------------
# Site Manager API Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_hosts(
    page_size: int = 25,
    next_token: str | None = None,
) -> str:
    """List all UniFi hosts (consoles/gateways) associated with your account.

    Returns host details including type, IP address, firmware version,
    and connectivity status. Use this to get an overview of all your
    UniFi controllers and gateways.

    Args:
        page_size: Number of hosts per page (default 25).
        next_token: Pagination token from a previous response to get the next page.
    """
    client: UniFiClient = _current_bundle().site_manager
    try:
        data = await client.list_hosts(page_size=page_size, next_token=next_token)
        return format_hosts(data)
    except UniFiApiError as e:
        return _error_response(e)


@mcp.tool()
async def get_host(host_id: str) -> str:
    """Get detailed information about a specific UniFi host.

    Returns comprehensive details about a single host including hardware info,
    firmware, network configuration, and reported state. Use list_hosts first
    to find host IDs.

    Args:
        host_id: The unique identifier of the host.
    """
    client: UniFiClient = _current_bundle().site_manager
    try:
        data = await client.get_host(host_id)
        return format_host_detail(data)
    except UniFiApiError as e:
        return _error_response(e)


@mcp.tool()
async def list_sites(
    page_size: int = 25,
    next_token: str | None = None,
) -> str:
    """List all UniFi Network sites across all hosts in your account.

    Returns site information including name, timezone, device/client counts,
    ISP info, and permissions. Sites are logical groupings of devices under
    a UniFi Network application.

    Args:
        page_size: Number of sites per page (default 25).
        next_token: Pagination token from a previous response to get the next page.
    """
    client: UniFiClient = _current_bundle().site_manager
    try:
        data = await client.list_sites(page_size=page_size, next_token=next_token)
        return format_sites(data)
    except UniFiApiError as e:
        return _error_response(e)


@mcp.tool()
async def list_devices(
    host_ids: list[str] | None = None,
    time: str | None = None,
    page_size: int = 25,
    next_token: str | None = None,
) -> str:
    """List all UniFi network devices (access points, switches, gateways, etc.).

    Returns device details including model, firmware, IP, MAC address, status,
    and uptime. Can be filtered by specific hosts.

    Args:
        host_ids: Optional list of host IDs to filter devices by specific hosts.
        time: Optional ISO 8601 timestamp to filter by last update time.
        page_size: Number of items per page (default 25).
        next_token: Pagination token from a previous response to get the next page.
    """
    client: UniFiClient = _current_bundle().site_manager
    try:
        data = await client.list_devices(
            host_ids=host_ids, time=time, page_size=page_size, next_token=next_token
        )
        return format_devices(data)
    except UniFiApiError as e:
        return _error_response(e)


@mcp.tool()
async def get_isp_metrics(
    metric_type: str,
    duration: str | None = None,
    begin_timestamp: str | None = None,
    end_timestamp: str | None = None,
) -> str:
    """Get ISP performance metrics across all sites.

    Returns latency, download/upload speed, uptime, and packet loss data.
    5-minute metrics are available for 24h, 1-hour metrics for 30 days.

    Args:
        metric_type: Interval granularity - "5m" for 5-minute or "1h" for hourly.
        duration: Lookback duration ("24h", "7d", "30d"). Cannot be used with timestamps.
        begin_timestamp: Start time in ISO 8601 format. Use with end_timestamp.
        end_timestamp: End time in ISO 8601 format. Use with begin_timestamp.
    """
    client: UniFiClient = _current_bundle().site_manager
    try:
        data = await client.get_isp_metrics(
            metric_type=metric_type,
            duration=duration,
            begin_timestamp=begin_timestamp,
            end_timestamp=end_timestamp,
        )
        return format_isp_metrics(data)
    except UniFiApiError as e:
        return _error_response(e)


@mcp.tool()
async def query_isp_metrics(
    metric_type: str,
    sites: list[dict[str, str]],
    begin_timestamp: str | None = None,
    end_timestamp: str | None = None,
) -> str:
    """Query ISP metrics for specific sites.

    Returns ISP performance data filtered to specified sites. Use list_sites
    first to get site and host IDs.

    Args:
        metric_type: Interval granularity - "5m" for 5-minute or "1h" for hourly.
        sites: List of site selectors, each a dict with "hostId" and "siteId" keys.
               Optionally include "beginTimestamp" and "endTimestamp" per site.
        begin_timestamp: Global start time in ISO 8601 format (optional).
        end_timestamp: Global end time in ISO 8601 format (optional).
    """
    client: UniFiClient = _current_bundle().site_manager
    try:
        data = await client.query_isp_metrics(
            metric_type=metric_type,
            sites=sites,
            begin_timestamp=begin_timestamp,
            end_timestamp=end_timestamp,
        )
        return format_isp_metrics(data)
    except UniFiApiError as e:
        return _error_response(e)


@mcp.tool()
async def get_sdwan_config(
    config_id: str | None = None,
    include_status: bool = False,
) -> str:
    """Get SD-WAN configurations and optionally their deployment status.

    Without config_id: lists all SD-WAN configurations.
    With config_id: returns the detailed configuration.
    With include_status=True: also fetches the deployment status.

    Args:
        config_id: Optional SD-WAN config ID. Omit to list all configs.
        include_status: If True and config_id is provided, also fetch deployment status.
    """
    client: UniFiClient = _current_bundle().site_manager
    try:
        if config_id is None:
            data = await client.list_sdwan_configs()
            return format_sdwan_configs(data)

        parts: list[str] = []
        data = await client.get_sdwan_config(config_id)
        parts.append("## Configuration\n")
        parts.append(format_sdwan_config_detail(data))

        if include_status:
            status_data = await client.get_sdwan_config_status(config_id)
            parts.append("\n\n## Deployment Status\n")
            parts.append(format_sdwan_config_status(status_data))

        return "\n".join(parts)
    except UniFiApiError as e:
        return _error_response(e)


# ---------------------------------------------------------------------------
# Mobility API Tools (cloud — UMR mobile routers)
# ---------------------------------------------------------------------------


@mcp.tool()
async def mobility_list_workspaces() -> str:
    """List UniFi Mobility workspaces (mobile-routing cloud sites) you can access.

    Returns each workspace's name, ID, owner flag, and status. Use the
    workspace ID with the other mobility_* tools. Requires an API key with
    the `mobility` app scope.
    """
    try:
        client = _get_mobility_client()
        data = await client.list_workspaces()
        return format_mobility_workspaces(data)
    except MobilityApiError as e:
        return _mobility_error_response(e)


@mcp.tool()
async def mobility_list_admins(workspace_id: str) -> str:
    """List admins of a Mobility workspace with their mobile-routing permissions.

    Args:
        workspace_id: The workspace UUID (from mobility_list_workspaces).
    """
    try:
        client = _get_mobility_client()
        data = await client.list_workspace_admins(workspace_id)
        return format_mobility_admins(data)
    except MobilityApiError as e:
        return _mobility_error_response(e)


@mcp.tool()
async def mobility_list_devices(
    workspace_id: str,
    offset: int = 0,
    limit: int = 200,
) -> str:
    """List UniFi Mobile Router (UMR) devices in a workspace.

    Args:
        workspace_id: The workspace UUID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 200, max 200).
    """
    try:
        client = _get_mobility_client()
        data = await client.list_devices(workspace_id, limit=limit, offset=offset)
        return format_mobility_devices(data)
    except MobilityApiError as e:
        return _mobility_error_response(e)


@mcp.tool()
async def mobility_get_device(workspace_id: str, device_id: str) -> str:
    """Get full detail for a Mobility device (WAN, cellular, WiFi, VPN, GPS, subscription).

    Args:
        workspace_id: The workspace UUID.
        device_id: The device UUID (from mobility_list_devices).
    """
    try:
        client = _get_mobility_client()
        data = await client.get_device(workspace_id, device_id)
        return format_mobility_device_detail(data)
    except MobilityApiError as e:
        return _mobility_error_response(e)


@mcp.tool()
async def mobility_list_device_clients(
    workspace_id: str,
    device_id: str,
    offset: int = 0,
    limit: int = 200,
) -> str:
    """List clients (online, offline, blocked) connected to a Mobility device.

    Args:
        workspace_id: The workspace UUID.
        device_id: The device UUID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 200, max 200).
    """
    try:
        client = _get_mobility_client()
        data = await client.list_device_clients(
            workspace_id, device_id, limit=limit, offset=offset
        )
        return format_mobility_device_clients(data)
    except MobilityApiError as e:
        return _mobility_error_response(e)


@mcp.tool()
async def mobility_update_device_name(
    workspace_id: str,
    device_id: str,
    name: str,
) -> str:
    """Rename a Mobility device (requires write:mobility scope and workspace Admin).

    Args:
        workspace_id: The workspace UUID.
        device_id: The device UUID.
        name: New display name (1-32 characters).
    """
    try:
        client = _get_mobility_client()
        result = await client.update_device_name(workspace_id, device_id, name)
        return format_mobility_result(result, "Device name updated")
    except MobilityApiError as e:
        return _mobility_error_response(e)


@mcp.tool()
async def mobility_update_device_network(
    workspace_id: str,
    device_id: str,
    data: dict,
) -> str:
    """Update a Mobility device's LAN / DHCP settings (partial update, Admin only).

    Only provided fields are applied. WAN, IPv6, and internet source are not
    configurable here.

    Args:
        workspace_id: The workspace UUID.
        device_id: The device UUID.
        data: Any of host_address, dhcp_mode ("dhcp"/"none"), dhcp_range_start,
              dhcp_range_stop, dhcp_lease_time (seconds, 0 = infinite).
    """
    try:
        client = _get_mobility_client()
        result = await client.update_device_network(workspace_id, device_id, data)
        return format_mobility_result(result, "Device network settings updated")
    except MobilityApiError as e:
        return _mobility_error_response(e)


@mcp.tool()
async def mobility_update_device_wireless(
    workspace_id: str,
    device_id: str,
    ssid: str,
    password: str,
) -> str:
    """Replace a Mobility device's WiFi SSID and WPA2 password (Admin only).

    Both fields are required. Channel, TX power, and security protocol are
    not configurable.

    Args:
        workspace_id: The workspace UUID.
        device_id: The device UUID.
        ssid: New SSID (1-32 characters).
        password: New WPA2-PSK password (8-63 characters).
    """
    try:
        client = _get_mobility_client()
        result = await client.update_device_wireless(
            workspace_id, device_id, {"ssid": ssid, "password": password}
        )
        return format_mobility_result(result, "Device WiFi settings updated")
    except MobilityApiError as e:
        return _mobility_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — Info
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_info() -> str:
    """Get UniFi Network application info and list all local sites.

    Returns application version and details, plus all sites configured
    on the local UniFi console. Use this first to discover site IDs
    needed by other network_* tools.
    """
    try:
        client = _get_network_client()
        info = await client.get_info()
        sites = await client.list_sites()
        parts = [format_network_info(info), "", format_network_sites(sites)]
        return "\n".join(parts)
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — Devices
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_list_devices(
    site_id: str,
    offset: int = 0,
    limit: int = 25,
) -> str:
    """List all adopted devices on a local UniFi site.

    Args:
        site_id: The site ID (get from network_info).
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_devices(site_id, offset=offset, limit=limit)
        return format_network_devices(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_get_device(
    site_id: str,
    device_id: str,
    include_statistics: bool = False,
) -> str:
    """Get detailed information about a specific device.

    Args:
        site_id: The site ID.
        device_id: The device ID.
        include_statistics: If True, also fetch latest device statistics.
    """
    try:
        client = _get_network_client()
        data = await client.get_device(site_id, device_id)
        parts: list[str] = [format_network_device_detail(data)]

        if include_statistics:
            stats = await client.get_device_statistics(site_id, device_id)
            parts.append("\n\n## Latest Statistics\n")
            parts.append(format_network_device_statistics(stats))

        return "\n".join(parts)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_device_action(
    site_id: str,
    device_id: str,
    action: str,
) -> str:
    """Execute an action on a UniFi device (restart, locate, adopt).

    Args:
        site_id: The site ID.
        device_id: The device ID.
        action: The action to execute (e.g. "restart", "locate", "adopt").
    """
    try:
        client = _get_network_client()
        data = await client.execute_device_action(
            site_id, device_id, {"action": action}
        )
        return format_action_result(data)
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — Clients
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_list_clients(
    site_id: str,
    offset: int = 0,
    limit: int = 25,
) -> str:
    """List all connected clients on a local UniFi site.

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_clients(site_id, offset=offset, limit=limit)
        return format_network_clients(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_get_client(
    site_id: str,
    client_id: str,
) -> str:
    """Get detailed information about a specific connected client.

    Args:
        site_id: The site ID.
        client_id: The client ID.
    """
    try:
        client = _get_network_client()
        data = await client.get_client(site_id, client_id)
        return format_network_client_detail(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_client_action(
    site_id: str,
    client_id: str,
    action: str,
) -> str:
    """Execute an action on a connected client (block, reconnect).

    Args:
        site_id: The site ID.
        client_id: The client ID.
        action: The action to execute (e.g. "block", "reconnect").
    """
    try:
        client = _get_network_client()
        data = await client.execute_client_action(
            site_id, client_id, {"action": action}
        )
        return format_action_result(data)
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — Networks
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_list_networks(
    site_id: str,
    offset: int = 0,
    limit: int = 25,
) -> str:
    """List all configured networks (VLANs) on a local UniFi site.

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_networks(site_id, offset=offset, limit=limit)
        return format_network_networks(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_get_network(
    site_id: str,
    network_id: str,
) -> str:
    """Get detailed information about a specific network.

    Args:
        site_id: The site ID.
        network_id: The network ID.
    """
    try:
        client = _get_network_client()
        data = await client.get_network(site_id, network_id)
        return format_network_network_detail(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_create_network(
    site_id: str,
    data: dict,
) -> str:
    """Create a new network on a local UniFi site.

    Args:
        site_id: The site ID.
        data: Network configuration (name, vlanId, etc.).
    """
    try:
        client = _get_network_client()
        result = await client.create_network(site_id, data)
        return format_crud_result(result, "Network created")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_update_network(
    site_id: str,
    network_id: str,
    data: dict,
) -> str:
    """Update an existing network on a local UniFi site.

    Args:
        site_id: The site ID.
        network_id: The network ID to update.
        data: Updated network configuration.
    """
    try:
        client = _get_network_client()
        result = await client.update_network(site_id, network_id, data)
        return format_crud_result(result, "Network updated")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_delete_network(
    site_id: str,
    network_id: str,
) -> str:
    """Delete a network from a local UniFi site.

    Args:
        site_id: The site ID.
        network_id: The network ID to delete.
    """
    try:
        client = _get_network_client()
        result = await client.delete_network(site_id, network_id)
        return format_crud_result(result, "Network deleted")
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — WiFi
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_list_wifi(
    site_id: str,
    offset: int = 0,
    limit: int = 25,
) -> str:
    """List all WiFi broadcasts (SSIDs) on a local UniFi site.

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_wifi(site_id, offset=offset, limit=limit)
        return format_network_wifi(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_get_wifi(
    site_id: str,
    wifi_id: str,
) -> str:
    """Get detailed information about a specific WiFi broadcast (SSID).

    Args:
        site_id: The site ID.
        wifi_id: The WiFi broadcast ID.
    """
    try:
        client = _get_network_client()
        data = await client.get_wifi(site_id, wifi_id)
        return format_network_wifi_detail(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_create_wifi(
    site_id: str,
    data: dict,
) -> str:
    """Create a new WiFi broadcast (SSID) on a local UniFi site.

    Args:
        site_id: The site ID.
        data: WiFi configuration (name, security, etc.).
    """
    try:
        client = _get_network_client()
        result = await client.create_wifi(site_id, data)
        return format_crud_result(result, "WiFi broadcast created")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_update_wifi(
    site_id: str,
    wifi_id: str,
    data: dict,
) -> str:
    """Update an existing WiFi broadcast (SSID) on a local UniFi site.

    Args:
        site_id: The site ID.
        wifi_id: The WiFi broadcast ID to update.
        data: Updated WiFi configuration.
    """
    try:
        client = _get_network_client()
        result = await client.update_wifi(site_id, wifi_id, data)
        return format_crud_result(result, "WiFi broadcast updated")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_delete_wifi(
    site_id: str,
    wifi_id: str,
) -> str:
    """Delete a WiFi broadcast (SSID) from a local UniFi site.

    Args:
        site_id: The site ID.
        wifi_id: The WiFi broadcast ID to delete.
    """
    try:
        client = _get_network_client()
        result = await client.delete_wifi(site_id, wifi_id)
        return format_crud_result(result, "WiFi broadcast deleted")
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — Firewall
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_list_firewall_zones(
    site_id: str,
    offset: int = 0,
    limit: int = 25,
) -> str:
    """List firewall zones on a local UniFi site.

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_firewall_zones(site_id, offset=offset, limit=limit)
        return format_network_firewall_zones(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_list_firewall_policies(
    site_id: str,
    offset: int = 0,
    limit: int = 25,
) -> str:
    """List firewall policies on a local UniFi site.

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_firewall_policies(site_id, offset=offset, limit=limit)
        return format_network_firewall_policies(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_create_firewall_policy(
    site_id: str,
    data: dict,
) -> str:
    """Create a new firewall policy on a local UniFi site.

    Args:
        site_id: The site ID.
        data: Firewall policy configuration.
    """
    try:
        client = _get_network_client()
        result = await client.create_firewall_policy(site_id, data)
        return format_crud_result(result, "Firewall policy created")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_update_firewall_policy(
    site_id: str,
    policy_id: str,
    data: dict,
) -> str:
    """Update an existing firewall policy on a local UniFi site.

    Args:
        site_id: The site ID.
        policy_id: The firewall policy ID to update.
        data: Updated firewall policy configuration.
    """
    try:
        client = _get_network_client()
        result = await client.update_firewall_policy(site_id, policy_id, data)
        return format_crud_result(result, "Firewall policy updated")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_delete_firewall_policy(
    site_id: str,
    policy_id: str,
) -> str:
    """Delete a firewall policy from a local UniFi site.

    Args:
        site_id: The site ID.
        policy_id: The firewall policy ID to delete.
    """
    try:
        client = _get_network_client()
        result = await client.delete_firewall_policy(site_id, policy_id)
        return format_crud_result(result, "Firewall policy deleted")
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — DNS
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_list_dns_policies(
    site_id: str,
    offset: int = 0,
    limit: int = 25,
) -> str:
    """List DNS filtering policies on a local UniFi site.

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_dns_policies(site_id, offset=offset, limit=limit)
        return format_network_dns_policies(data)
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — Vouchers
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_list_vouchers(
    site_id: str,
    offset: int = 0,
    limit: int = 25,
) -> str:
    """List hotspot vouchers on a local UniFi site.

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_vouchers(site_id, offset=offset, limit=limit)
        return format_network_vouchers(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_create_vouchers(
    site_id: str,
    data: dict,
) -> str:
    """Create hotspot vouchers on a local UniFi site.

    Args:
        site_id: The site ID.
        data: Voucher configuration (duration, quota, count, etc.).
    """
    try:
        client = _get_network_client()
        result = await client.create_vouchers(site_id, data)
        return format_crud_result(result, "Vouchers created")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_delete_voucher(
    site_id: str,
    voucher_id: str,
) -> str:
    """Delete a hotspot voucher from a local UniFi site.

    Args:
        site_id: The site ID.
        voucher_id: The voucher ID to delete.
    """
    try:
        client = _get_network_client()
        result = await client.delete_voucher(site_id, voucher_id)
        return format_crud_result(result, "Voucher deleted")
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — Supporting resources
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_list_wans(
    site_id: str,
    offset: int = 0,
    limit: int = 25,
) -> str:
    """List WAN interfaces on a local UniFi site.

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_wans(site_id, offset=offset, limit=limit)
        return format_network_wans(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_list_vpn_tunnels(
    site_id: str,
    offset: int = 0,
    limit: int = 25,
) -> str:
    """List site-to-site VPN tunnels on a local UniFi site.

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_vpn_tunnels(site_id, offset=offset, limit=limit)
        return format_network_vpn_tunnels(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_list_vpn_servers(
    site_id: str,
    offset: int = 0,
    limit: int = 25,
) -> str:
    """List VPN servers on a local UniFi site.

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_vpn_servers(site_id, offset=offset, limit=limit)
        return format_network_vpn_servers(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_list_radius_profiles(
    site_id: str,
    offset: int = 0,
    limit: int = 25,
) -> str:
    """List RADIUS profiles on a local UniFi site.

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_radius_profiles(site_id, offset=offset, limit=limit)
        return format_network_radius_profiles(data)
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — Device adoption & ports
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_list_pending_devices(offset: int = 0, limit: int = 25) -> str:
    """List devices pending adoption across the local Network application.

    Args:
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_pending_devices(offset=offset, limit=limit)
        return format_network_pending_devices(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_adopt_device(
    site_id: str,
    mac_address: str,
    ignore_device_limit: bool = False,
) -> str:
    """Adopt a pending device onto a local UniFi site.

    Args:
        site_id: The site ID.
        mac_address: MAC address of the device to adopt.
        ignore_device_limit: Adopt even if the device limit is reached.
    """
    try:
        client = _get_network_client()
        data = await client.adopt_device(
            site_id,
            {"macAddress": mac_address, "ignoreDeviceLimit": ignore_device_limit},
        )
        return format_network_device_detail(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_remove_device(site_id: str, device_id: str) -> str:
    """Remove (unadopt) a device from a local UniFi site. Online devices are factory reset.

    Args:
        site_id: The site ID.
        device_id: The device ID to remove.
    """
    try:
        client = _get_network_client()
        result = await client.remove_device(site_id, device_id)
        return format_crud_result(result, "Device removed")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_port_action(
    site_id: str,
    device_id: str,
    port_idx: int,
    action: str,
) -> str:
    """Execute an action on a device port (e.g. PoE power-cycle).

    Args:
        site_id: The site ID.
        device_id: The device ID.
        port_idx: The port index (1-based).
        action: The action name (e.g. "POWER_CYCLE").
    """
    try:
        client = _get_network_client()
        result = await client.execute_port_action(
            site_id, device_id, port_idx, {"action": action}
        )
        return format_action_result(result)
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — ACL rules
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_list_acl_rules(
    site_id: str, offset: int = 0, limit: int = 25
) -> str:
    """List ACL rules on a local UniFi site.

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_acl_rules(site_id, offset=offset, limit=limit)
        return format_network_acl_rules(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_get_acl_rule(site_id: str, acl_rule_id: str) -> str:
    """Get a specific ACL rule.

    Args:
        site_id: The site ID.
        acl_rule_id: The ACL rule ID.
    """
    try:
        client = _get_network_client()
        data = await client.get_acl_rule(site_id, acl_rule_id)
        return format_network_detail(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_create_acl_rule(site_id: str, data: dict) -> str:
    """Create a user-defined ACL rule on a local UniFi site.

    Args:
        site_id: The site ID.
        data: ACL rule config (type "IPV4"/"MAC", action, name, filters, etc.).
    """
    try:
        client = _get_network_client()
        result = await client.create_acl_rule(site_id, data)
        return format_crud_result(result, "ACL rule created")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_update_acl_rule(
    site_id: str, acl_rule_id: str, data: dict
) -> str:
    """Update a user-defined ACL rule.

    Args:
        site_id: The site ID.
        acl_rule_id: The ACL rule ID.
        data: Updated ACL rule config.
    """
    try:
        client = _get_network_client()
        result = await client.update_acl_rule(site_id, acl_rule_id, data)
        return format_crud_result(result, "ACL rule updated")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_delete_acl_rule(site_id: str, acl_rule_id: str) -> str:
    """Delete a user-defined ACL rule.

    Args:
        site_id: The site ID.
        acl_rule_id: The ACL rule ID.
    """
    try:
        client = _get_network_client()
        result = await client.delete_acl_rule(site_id, acl_rule_id)
        return format_crud_result(result, "ACL rule deleted")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_acl_rule_ordering(
    site_id: str, ordered_acl_rule_ids: list[str] | None = None
) -> str:
    """Get or set the user-defined ACL rule ordering (lower index = higher priority).

    Args:
        site_id: The site ID.
        ordered_acl_rule_ids: If provided, reorder rules to this exact sequence.
                              If omitted, return the current ordering.
    """
    try:
        client = _get_network_client()
        if ordered_acl_rule_ids is None:
            data = await client.get_acl_rule_ordering(site_id)
        else:
            data = await client.update_acl_rule_ordering(
                site_id, {"orderedAclRuleIds": ordered_acl_rule_ids}
            )
        return format_network_detail(data)
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — DNS policy CRUD
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_get_dns_policy(site_id: str, dns_policy_id: str) -> str:
    """Get a specific DNS policy.

    Args:
        site_id: The site ID.
        dns_policy_id: The DNS policy ID.
    """
    try:
        client = _get_network_client()
        data = await client.get_dns_policy(site_id, dns_policy_id)
        return format_network_detail(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_create_dns_policy(site_id: str, data: dict) -> str:
    """Create a DNS policy (A/AAAA/CNAME/MX/SRV/TXT record or forward domain).

    Args:
        site_id: The site ID.
        data: DNS policy config (type, enabled, domain, and record-specific fields).
    """
    try:
        client = _get_network_client()
        result = await client.create_dns_policy(site_id, data)
        return format_crud_result(result, "DNS policy created")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_update_dns_policy(
    site_id: str, dns_policy_id: str, data: dict
) -> str:
    """Update an existing DNS policy.

    Args:
        site_id: The site ID.
        dns_policy_id: The DNS policy ID.
        data: Updated DNS policy config.
    """
    try:
        client = _get_network_client()
        result = await client.update_dns_policy(site_id, dns_policy_id, data)
        return format_crud_result(result, "DNS policy updated")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_delete_dns_policy(site_id: str, dns_policy_id: str) -> str:
    """Delete a DNS policy.

    Args:
        site_id: The site ID.
        dns_policy_id: The DNS policy ID.
    """
    try:
        client = _get_network_client()
        result = await client.delete_dns_policy(site_id, dns_policy_id)
        return format_crud_result(result, "DNS policy deleted")
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — Firewall zones & policy ordering
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_get_firewall_zone(site_id: str, firewall_zone_id: str) -> str:
    """Get a specific firewall zone.

    Args:
        site_id: The site ID.
        firewall_zone_id: The firewall zone ID.
    """
    try:
        client = _get_network_client()
        data = await client.get_firewall_zone(site_id, firewall_zone_id)
        return format_network_detail(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_create_firewall_zone(site_id: str, data: dict) -> str:
    """Create a custom firewall zone.

    Args:
        site_id: The site ID.
        data: Zone config ({"name": ..., "networkIds": [...]}).
    """
    try:
        client = _get_network_client()
        result = await client.create_firewall_zone(site_id, data)
        return format_crud_result(result, "Firewall zone created")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_update_firewall_zone(
    site_id: str, firewall_zone_id: str, data: dict
) -> str:
    """Update a firewall zone.

    Args:
        site_id: The site ID.
        firewall_zone_id: The firewall zone ID.
        data: Updated zone config.
    """
    try:
        client = _get_network_client()
        result = await client.update_firewall_zone(site_id, firewall_zone_id, data)
        return format_crud_result(result, "Firewall zone updated")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_delete_firewall_zone(site_id: str, firewall_zone_id: str) -> str:
    """Delete a custom firewall zone.

    Args:
        site_id: The site ID.
        firewall_zone_id: The firewall zone ID.
    """
    try:
        client = _get_network_client()
        result = await client.delete_firewall_zone(site_id, firewall_zone_id)
        return format_crud_result(result, "Firewall zone deleted")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_get_firewall_policy(site_id: str, policy_id: str) -> str:
    """Get a specific firewall policy.

    Args:
        site_id: The site ID.
        policy_id: The firewall policy ID.
    """
    try:
        client = _get_network_client()
        data = await client.get_firewall_policy(site_id, policy_id)
        return format_network_detail(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_firewall_policy_ordering(
    site_id: str,
    source_zone_id: str,
    destination_zone_id: str,
    ordered_policy_ids: dict | None = None,
) -> str:
    """Get or set firewall policy ordering for a source/destination zone pair.

    Args:
        site_id: The site ID.
        source_zone_id: Source firewall zone ID.
        destination_zone_id: Destination firewall zone ID.
        ordered_policy_ids: If provided, an object with "beforeSystemDefined" and
                            "afterSystemDefined" lists of policy IDs to apply.
                            Omit to read the current ordering.
    """
    try:
        client = _get_network_client()
        if ordered_policy_ids is None:
            data = await client.get_firewall_policy_ordering(
                site_id, source_zone_id, destination_zone_id
            )
        else:
            data = await client.update_firewall_policy_ordering(
                site_id,
                source_zone_id,
                destination_zone_id,
                {"orderedFirewallPolicyIds": ordered_policy_ids},
            )
        return format_network_detail(data)
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — Traffic matching lists
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_list_traffic_matching_lists(
    site_id: str, offset: int = 0, limit: int = 25
) -> str:
    """List traffic matching lists (IP/port lists used by firewall policies).

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_traffic_matching_lists(
            site_id, offset=offset, limit=limit
        )
        return format_network_traffic_matching_lists(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_get_traffic_matching_list(site_id: str, list_id: str) -> str:
    """Get a specific traffic matching list.

    Args:
        site_id: The site ID.
        list_id: The traffic matching list ID.
    """
    try:
        client = _get_network_client()
        data = await client.get_traffic_matching_list(site_id, list_id)
        return format_network_detail(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_create_traffic_matching_list(site_id: str, data: dict) -> str:
    """Create a traffic matching list.

    Args:
        site_id: The site ID.
        data: List config (type "IPV4_ADDRESSES"/"IPV6_ADDRESSES"/"PORTS", name, items).
    """
    try:
        client = _get_network_client()
        result = await client.create_traffic_matching_list(site_id, data)
        return format_crud_result(result, "Traffic matching list created")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_update_traffic_matching_list(
    site_id: str, list_id: str, data: dict
) -> str:
    """Update a traffic matching list.

    Args:
        site_id: The site ID.
        list_id: The traffic matching list ID.
        data: Updated list config.
    """
    try:
        client = _get_network_client()
        result = await client.update_traffic_matching_list(site_id, list_id, data)
        return format_crud_result(result, "Traffic matching list updated")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_delete_traffic_matching_list(site_id: str, list_id: str) -> str:
    """Delete a traffic matching list.

    Args:
        site_id: The site ID.
        list_id: The traffic matching list ID.
    """
    try:
        client = _get_network_client()
        result = await client.delete_traffic_matching_list(site_id, list_id)
        return format_crud_result(result, "Traffic matching list deleted")
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — Switching
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_list_lags(site_id: str, offset: int = 0, limit: int = 25) -> str:
    """List Link Aggregation Groups (LAGs) on a local UniFi site.

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_lags(site_id, offset=offset, limit=limit)
        return format_network_lags(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_get_lag(site_id: str, lag_id: str) -> str:
    """Get details of a specific LAG.

    Args:
        site_id: The site ID.
        lag_id: The LAG ID.
    """
    try:
        client = _get_network_client()
        data = await client.get_lag(site_id, lag_id)
        return format_network_detail(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_list_mc_lag_domains(
    site_id: str, offset: int = 0, limit: int = 25
) -> str:
    """List MC-LAG (multi-chassis LAG) domains on a local UniFi site.

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_mc_lag_domains(site_id, offset=offset, limit=limit)
        return format_network_mc_lag_domains(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_get_mc_lag_domain(site_id: str, mc_lag_domain_id: str) -> str:
    """Get details of a specific MC-LAG domain.

    Args:
        site_id: The site ID.
        mc_lag_domain_id: The MC-LAG domain ID.
    """
    try:
        client = _get_network_client()
        data = await client.get_mc_lag_domain(site_id, mc_lag_domain_id)
        return format_network_detail(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_list_switch_stacks(
    site_id: str, offset: int = 0, limit: int = 25
) -> str:
    """List switch stacks on a local UniFi site.

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_switch_stacks(site_id, offset=offset, limit=limit)
        return format_network_switch_stacks(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_get_switch_stack(site_id: str, switch_stack_id: str) -> str:
    """Get details of a specific switch stack.

    Args:
        site_id: The site ID.
        switch_stack_id: The switch stack ID.
    """
    try:
        client = _get_network_client()
        data = await client.get_switch_stack(site_id, switch_stack_id)
        return format_network_detail(data)
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Network API Tools — More supporting resources
# ---------------------------------------------------------------------------


@mcp.tool()
async def network_get_network_references(site_id: str, network_id: str) -> str:
    """List what references a network (clients, devices, routes, WiFi, NAT, etc.).

    Args:
        site_id: The site ID.
        network_id: The network ID.
    """
    try:
        client = _get_network_client()
        data = await client.get_network_references(site_id, network_id)
        return format_network_detail(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_list_device_tags(
    site_id: str, offset: int = 0, limit: int = 25
) -> str:
    """List device tags on a local UniFi site (used for WiFi broadcast assignment).

    Args:
        site_id: The site ID.
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_device_tags(site_id, offset=offset, limit=limit)
        return format_network_device_tags(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_list_countries(offset: int = 0, limit: int = 25) -> str:
    """List ISO country codes/names used for region-based configuration.

    Args:
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_countries(offset=offset, limit=limit)
        return format_network_countries(data)
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_list_dpi_applications(offset: int = 0, limit: int = 25) -> str:
    """List DPI-recognized applications (for firewall/traffic rules).

    Args:
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_dpi_applications(offset=offset, limit=limit)
        return format_network_dpi(data, "application")
    except NetworkApiError as e:
        return _network_error_response(e)


@mcp.tool()
async def network_list_dpi_categories(offset: int = 0, limit: int = 25) -> str:
    """List DPI application categories (for firewall/traffic rules).

    Args:
        offset: Pagination offset (default 0).
        limit: Items per page (default 25, max 200).
    """
    try:
        client = _get_network_client()
        data = await client.list_dpi_categories(offset=offset, limit=limit)
        return format_network_dpi(data, "category")
    except NetworkApiError as e:
        return _network_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Info
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_info() -> str:
    """Get UniFi Protect application info and NVR system status.

    Returns Protect application metadata and NVR details including
    firmware version, storage info, and recording settings.
    Use this first to verify Protect connectivity.
    """
    try:
        client = _get_protect_client()
        info = await client.get_app_info()
        nvr = await client.get_nvr()
        parts = [format_protect_app_info(info), "", format_protect_nvr(nvr)]
        return "\n".join(parts)
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Cameras
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_list_cameras() -> str:
    """List all cameras managed by UniFi Protect.

    Returns camera names, models, connection state, recording status,
    and firmware versions. Use this to discover camera IDs.
    """
    try:
        client = _get_protect_client()
        data = await client.list_cameras()
        return format_protect_cameras(data)
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_camera(camera_id: str) -> str:
    """Get detailed information about a specific Protect camera.

    Args:
        camera_id: The camera ID (get from protect_list_cameras).
    """
    try:
        client = _get_protect_client()
        data = await client.get_camera(camera_id)
        return format_protect_camera_detail(data)
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_update_camera(camera_id: str, data: dict) -> str:
    """Update a Protect camera's settings (name, OSD, LED, etc.).

    Args:
        camera_id: The camera ID.
        data: Fields to update (e.g. {"name": "Front Door"}).
    """
    try:
        client = _get_protect_client()
        result = await client.update_camera(camera_id, data)
        return format_protect_crud_result(result, "Camera updated")
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_camera_snapshot(camera_id: str) -> str:
    """Get a JPEG snapshot from a Protect camera.

    Returns the snapshot as a base64-encoded JPEG image.

    Args:
        camera_id: The camera ID.
    """
    try:
        client = _get_protect_client()
        image_bytes = await client.get_camera_snapshot(camera_id)
        b64 = base64.b64encode(image_bytes).decode("ascii")
        return f"![Camera snapshot](data:image/jpeg;base64,{b64})"
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Lights
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_list_lights() -> str:
    """List all lights managed by UniFi Protect.

    Returns light names, models, and motion detection state.
    """
    try:
        client = _get_protect_client()
        data = await client.list_lights()
        return format_protect_lights(data)
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_light(light_id: str) -> str:
    """Get detailed information about a specific Protect light.

    Args:
        light_id: The light ID.
    """
    try:
        client = _get_protect_client()
        data = await client.get_light(light_id)
        return format_protect_light_detail(data)
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_update_light(light_id: str, data: dict) -> str:
    """Update a Protect light's settings.

    Args:
        light_id: The light ID.
        data: Fields to update.
    """
    try:
        client = _get_protect_client()
        result = await client.update_light(light_id, data)
        return format_protect_crud_result(result, "Light updated")
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Sensors
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_list_sensors() -> str:
    """List all sensors managed by UniFi Protect.

    Returns sensor names, models, and current readings (temperature,
    humidity, light level).
    """
    try:
        client = _get_protect_client()
        data = await client.list_sensors()
        return format_protect_sensors(data)
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_sensor(sensor_id: str) -> str:
    """Get detailed information about a specific Protect sensor.

    Args:
        sensor_id: The sensor ID.
    """
    try:
        client = _get_protect_client()
        data = await client.get_sensor(sensor_id)
        return format_protect_sensor_detail(data)
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_update_sensor(sensor_id: str, data: dict) -> str:
    """Update a Protect sensor's settings.

    Args:
        sensor_id: The sensor ID.
        data: Fields to update.
    """
    try:
        client = _get_protect_client()
        result = await client.update_sensor(sensor_id, data)
        return format_protect_crud_result(result, "Sensor updated")
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Chimes
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_list_chimes() -> str:
    """List all chimes managed by UniFi Protect."""
    try:
        client = _get_protect_client()
        data = await client.list_chimes()
        return format_protect_chimes(data)
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_chime(chime_id: str) -> str:
    """Get detailed information about a specific Protect chime.

    Args:
        chime_id: The chime ID.
    """
    try:
        client = _get_protect_client()
        data = await client.get_chime(chime_id)
        return format_protect_chime_detail(data)
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_update_chime(chime_id: str, data: dict) -> str:
    """Update a Protect chime's settings.

    Args:
        chime_id: The chime ID.
        data: Fields to update.
    """
    try:
        client = _get_protect_client()
        result = await client.update_chime(chime_id, data)
        return format_protect_crud_result(result, "Chime updated")
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Events
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_list_events() -> str:
    """List recent Protect events (motion, smart detections, etc.).

    Returns up to 10,000 events. Output is truncated to the 50 most
    recent for readability.
    """
    try:
        client = _get_protect_client()
        data = await client.list_events()
        return format_protect_events(data)
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Liveviews
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_list_liveviews() -> str:
    """List all liveviews configured in UniFi Protect."""
    try:
        client = _get_protect_client()
        data = await client.list_liveviews()
        return format_protect_liveviews(data)
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_liveview(liveview_id: str) -> str:
    """Get detailed information about a specific Protect liveview.

    Args:
        liveview_id: The liveview ID.
    """
    try:
        client = _get_protect_client()
        data = await client.get_liveview(liveview_id)
        return format_protect_liveview_detail(data)
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_create_liveview(data: dict) -> str:
    """Create a new liveview in UniFi Protect.

    Args:
        data: Liveview configuration (name, slots, etc.).
    """
    try:
        client = _get_protect_client()
        result = await client.create_liveview(data)
        return format_protect_crud_result(result, "Liveview created")
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_update_liveview(liveview_id: str, data: dict) -> str:
    """Update an existing liveview in UniFi Protect.

    Args:
        liveview_id: The liveview ID.
        data: Updated liveview configuration.
    """
    try:
        client = _get_protect_client()
        result = await client.update_liveview(liveview_id, data)
        return format_protect_crud_result(result, "Liveview updated")
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Viewers
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_list_viewers() -> str:
    """List all viewers (Viewport devices) in UniFi Protect."""
    try:
        client = _get_protect_client()
        data = await client.list_viewers()
        return format_protect_viewers(data)
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_viewer(viewer_id: str) -> str:
    """Get detailed information about a specific Protect viewer.

    Args:
        viewer_id: The viewer ID.
    """
    try:
        client = _get_protect_client()
        data = await client.get_viewer(viewer_id)
        return format_protect_viewer_detail(data)
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_update_viewer(viewer_id: str, data: dict) -> str:
    """Update a Protect viewer's settings.

    Args:
        viewer_id: The viewer ID.
        data: Fields to update.
    """
    try:
        client = _get_protect_client()
        result = await client.update_viewer(viewer_id, data)
        return format_protect_crud_result(result, "Viewer updated")
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Camera PTZ, streams & talkback
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_camera_ptz_goto(camera_id: str, slot: str) -> str:
    """Move a PTZ camera to a preset position.

    Args:
        camera_id: The camera ID.
        slot: Preset slot as a string ("-1" is the home preset, ">=0" others).
    """
    try:
        client = _get_protect_client()
        result = await client.ptz_goto_preset(camera_id, slot)
        return format_protect_crud_result(result, "PTZ move")
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_camera_ptz_patrol(
    camera_id: str, slot: str | None = None
) -> str:
    """Start or stop a PTZ camera patrol.

    Args:
        camera_id: The camera ID.
        slot: Patrol slot ("0"-"4") to start. Omit to stop the active patrol.
    """
    try:
        client = _get_protect_client()
        if slot is None:
            result = await client.ptz_stop_patrol(camera_id)
            return format_protect_crud_result(result, "PTZ patrol stop")
        result = await client.ptz_start_patrol(camera_id, slot)
        return format_protect_crud_result(result, "PTZ patrol start")
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_camera_rtsps_streams(
    camera_id: str,
    create_qualities: list[str] | None = None,
    delete_qualities: list[str] | None = None,
) -> str:
    """Manage a camera's RTSPS stream URLs.

    With no arguments, returns the existing stream URLs. Provide
    create_qualities to (re)create streams, or delete_qualities to remove them.
    Qualities: "high", "medium", "low", "package" (package cameras only).

    Args:
        camera_id: The camera ID.
        create_qualities: Quality levels to create streams for.
        delete_qualities: Quality levels to delete streams for.
    """
    try:
        client = _get_protect_client()
        if create_qualities:
            data = await client.create_camera_rtsps_streams(
                camera_id, create_qualities
            )
        elif delete_qualities:
            data = await client.delete_camera_rtsps_streams(
                camera_id, delete_qualities
            )
        else:
            data = await client.get_camera_rtsps_streams(camera_id)
        return format_protect_device_detail(data)
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_camera_talkback_session(camera_id: str) -> str:
    """Create a talkback session for a camera (returns stream URL and audio config).

    Args:
        camera_id: The camera ID.
    """
    try:
        client = _get_protect_client()
        data = await client.create_camera_talkback_session(camera_id)
        return format_protect_device_detail(data)
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_camera_disable_mic(camera_id: str) -> str:
    """Permanently disable a camera's microphone. Cannot be undone without a reset.

    Args:
        camera_id: The camera ID.
    """
    try:
        client = _get_protect_client()
        result = await client.disable_camera_mic(camera_id)
        return format_protect_crud_result(result, "Microphone permanently disabled")
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Sirens
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_list_sirens() -> str:
    """List all sirens managed by UniFi Protect."""
    try:
        client = _get_protect_client()
        return format_protect_sirens(await client.list_sirens())
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_siren(siren_id: str) -> str:
    """Get detailed information about a specific siren.

    Args:
        siren_id: The siren ID.
    """
    try:
        client = _get_protect_client()
        return format_protect_device_detail(await client.get_siren(siren_id))
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_update_siren(siren_id: str, data: dict) -> str:
    """Update a siren's settings (name, volume, LED).

    Args:
        siren_id: The siren ID.
        data: Fields to update.
    """
    try:
        client = _get_protect_client()
        result = await client.update_siren(siren_id, data)
        return format_protect_crud_result(result, "Siren updated")
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_siren_control(
    siren_id: str,
    action: str,
    duration: int | None = None,
    volume: int | None = None,
) -> str:
    """Activate, stop, or test a siren.

    Args:
        siren_id: The siren ID.
        action: "play", "stop", or "test".
        duration: For "play", activation seconds (5/10/20/30; default 5).
        volume: For "test", volume 1-100 (defaults to configured device volume).
    """
    try:
        client = _get_protect_client()
        if action == "play":
            result = await client.play_siren(siren_id, duration)
        elif action == "stop":
            result = await client.stop_siren(siren_id)
        elif action == "test":
            result = await client.test_siren_sound(siren_id, volume)
        else:
            return "Invalid action. Use 'play', 'stop', or 'test'."
        return format_protect_crud_result(result, f"Siren {action}")
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Speakers
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_list_speakers() -> str:
    """List all speakers managed by UniFi Protect."""
    try:
        client = _get_protect_client()
        return format_protect_speakers(await client.list_speakers())
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_speaker(speaker_id: str) -> str:
    """Get detailed information about a specific speaker.

    Args:
        speaker_id: The speaker ID.
    """
    try:
        client = _get_protect_client()
        return format_protect_device_detail(await client.get_speaker(speaker_id))
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_update_speaker(speaker_id: str, data: dict) -> str:
    """Update a speaker's settings (name, volume, mic).

    Args:
        speaker_id: The speaker ID.
        data: Fields to update.
    """
    try:
        client = _get_protect_client()
        result = await client.update_speaker(speaker_id, data)
        return format_protect_crud_result(result, "Speaker updated")
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_test_speaker(speaker_id: str, volume: int | None = None) -> str:
    """Test a speaker's sound at the given volume.

    Args:
        speaker_id: The speaker ID.
        volume: Test volume 0-100 (defaults to configured device volume).
    """
    try:
        client = _get_protect_client()
        result = await client.test_speaker_sound(speaker_id, volume)
        return format_protect_crud_result(result, "Speaker test")
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Fobs
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_list_fobs() -> str:
    """List all key fobs managed by UniFi Protect."""
    try:
        client = _get_protect_client()
        return format_protect_fobs(await client.list_fobs())
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_fob(fob_id: str) -> str:
    """Get detailed information about a specific fob.

    Args:
        fob_id: The fob ID.
    """
    try:
        client = _get_protect_client()
        return format_protect_device_detail(await client.get_fob(fob_id))
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_update_fob(fob_id: str, data: dict) -> str:
    """Update a fob's settings (name).

    Args:
        fob_id: The fob ID.
        data: Fields to update.
    """
    try:
        client = _get_protect_client()
        result = await client.update_fob(fob_id, data)
        return format_protect_crud_result(result, "Fob updated")
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Relays
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_list_relays() -> str:
    """List all relays (UniFi Connect relays) managed by UniFi Protect."""
    try:
        client = _get_protect_client()
        return format_protect_relays(await client.list_relays())
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_relay(relay_id: str) -> str:
    """Get detailed information about a specific relay.

    Args:
        relay_id: The relay ID.
    """
    try:
        client = _get_protect_client()
        return format_protect_device_detail(await client.get_relay(relay_id))
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_update_relay(relay_id: str, data: dict) -> str:
    """Update a relay's settings (name, LED).

    Args:
        relay_id: The relay ID.
        data: Fields to update.
    """
    try:
        client = _get_protect_client()
        result = await client.update_relay(relay_id, data)
        return format_protect_crud_result(result, "Relay updated")
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_activate_relay_output(
    relay_id: str,
    output_id: int,
    state: str | None = None,
    pulse_duration: int | None = None,
) -> str:
    """Control a relay output (on/off/toggle, optional auto-off pulse).

    Args:
        relay_id: The relay ID.
        output_id: Output channel ID (0 or 1).
        state: "on" or "off". Omit to toggle the current state.
        pulse_duration: Auto-off duration in ms (only when state is "on").
    """
    try:
        client = _get_protect_client()
        body: dict[str, object] = {}
        if state is not None:
            body["state"] = state
        if pulse_duration is not None:
            body["pulseDuration"] = pulse_duration
        result = await client.activate_relay_output(
            relay_id, output_id, body or None
        )
        return format_protect_crud_result(result, "Relay output activated")
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Bridges & Link Stations
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_list_bridges() -> str:
    """List all bridges managed by UniFi Protect."""
    try:
        client = _get_protect_client()
        return format_protect_bridges(await client.list_bridges())
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_bridge(bridge_id: str) -> str:
    """Get detailed information about a specific bridge.

    Args:
        bridge_id: The bridge ID.
    """
    try:
        client = _get_protect_client()
        return format_protect_device_detail(await client.get_bridge(bridge_id))
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_update_bridge(bridge_id: str, data: dict) -> str:
    """Update a bridge's settings (name).

    Args:
        bridge_id: The bridge ID.
        data: Fields to update.
    """
    try:
        client = _get_protect_client()
        result = await client.update_bridge(bridge_id, data)
        return format_protect_crud_result(result, "Bridge updated")
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_list_link_stations() -> str:
    """List all link stations (non-alarm-hub gateways) managed by UniFi Protect."""
    try:
        client = _get_protect_client()
        return format_protect_link_stations(await client.list_link_stations())
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_link_station(link_station_id: str) -> str:
    """Get detailed information about a specific link station.

    Args:
        link_station_id: The link station ID.
    """
    try:
        client = _get_protect_client()
        return format_protect_device_detail(
            await client.get_link_station(link_station_id)
        )
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_update_link_station(link_station_id: str, data: dict) -> str:
    """Update a link station's settings (name).

    Args:
        link_station_id: The link station ID.
        data: Fields to update.
    """
    try:
        client = _get_protect_client()
        result = await client.update_link_station(link_station_id, data)
        return format_protect_crud_result(result, "Link station updated")
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Alarm Hubs
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_list_alarm_hubs() -> str:
    """List all alarm hubs managed by UniFi Protect."""
    try:
        client = _get_protect_client()
        return format_protect_alarm_hubs(await client.list_alarm_hubs())
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_alarm_hub(alarm_hub_id: str) -> str:
    """Get detailed information and status about a specific alarm hub.

    Args:
        alarm_hub_id: The alarm hub ID.
    """
    try:
        client = _get_protect_client()
        return format_protect_device_detail(
            await client.get_alarm_hub(alarm_hub_id)
        )
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_update_alarm_hub(alarm_hub_id: str, data: dict) -> str:
    """Update an alarm hub's settings (name).

    Args:
        alarm_hub_id: The alarm hub ID.
        data: Fields to update.
    """
    try:
        client = _get_protect_client()
        result = await client.update_alarm_hub(alarm_hub_id, data)
        return format_protect_crud_result(result, "Alarm hub updated")
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_trigger_alarm_hub_output(
    alarm_hub_id: str,
    output_id: int,
    enable: bool | None = None,
    delay: int | None = None,
    duration: int | None = None,
) -> str:
    """Trigger an alarm hub output channel (drive connected sirens, lights, etc.).

    Args:
        alarm_hub_id: The alarm hub ID.
        output_id: Output channel ID (0 or 1).
        enable: True to turn on, False to turn off. Omit to toggle.
        delay: Delay in ms before the output activates.
        duration: Duration in ms to keep active (0 = indefinite).
    """
    try:
        client = _get_protect_client()
        body: dict[str, object] = {}
        if enable is not None:
            body["enable"] = enable
        if delay is not None:
            body["delay"] = delay
        if duration is not None:
            body["duration"] = duration
        result = await client.trigger_alarm_hub_output(
            alarm_hub_id, output_id, body or None
        )
        return format_protect_crud_result(result, "Alarm hub output triggered")
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Arm Profiles & Alarm Manager (local alarm manager only)
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_list_arm_profiles() -> str:
    """List all arm profiles (local alarm manager only)."""
    try:
        client = _get_protect_client()
        return format_protect_arm_profiles(await client.list_arm_profiles())
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_create_arm_profile(data: dict) -> str:
    """Create an arm profile (local alarm manager only).

    Args:
        data: Profile config (name, automations, schedules, recordEverything,
              activationDelay).
    """
    try:
        client = _get_protect_client()
        result = await client.create_arm_profile(data)
        return format_protect_crud_result(result, "Arm profile created")
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_update_arm_profile(arm_profile_id: str, data: dict) -> str:
    """Update an arm profile (local alarm manager only).

    Args:
        arm_profile_id: The arm profile ID.
        data: Fields to update.
    """
    try:
        client = _get_protect_client()
        result = await client.update_arm_profile(arm_profile_id, data)
        return format_protect_crud_result(result, "Arm profile updated")
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_delete_arm_profile(arm_profile_id: str) -> str:
    """Delete an arm profile (local alarm manager only).

    Args:
        arm_profile_id: The arm profile ID.
    """
    try:
        client = _get_protect_client()
        result = await client.delete_arm_profile(arm_profile_id)
        return format_protect_crud_result(result, "Arm profile deleted")
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_arm_alarm(
    action: str,
    arm_profile_id: str | None = None,
) -> str:
    """Enable/disable the arm alarm or set the current arm profile.

    Args:
        action: "enable", "disable", or "set-profile".
        arm_profile_id: Required when action is "set-profile".
    """
    try:
        client = _get_protect_client()
        if action == "enable":
            result = await client.enable_arm_alarm()
        elif action == "disable":
            result = await client.disable_arm_alarm()
        elif action == "set-profile":
            if not arm_profile_id:
                return "arm_profile_id is required for 'set-profile'."
            result = await client.set_current_arm_profile(arm_profile_id)
        else:
            return "Invalid action. Use 'enable', 'disable', or 'set-profile'."
        return format_protect_crud_result(result, f"Arm alarm {action}")
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_send_alarm_webhook(trigger_id: str) -> str:
    """Send a webhook to the alarm manager to trigger alarms configured with this ID.

    Args:
        trigger_id: User-defined trigger string matching the alarm configuration.
    """
    try:
        client = _get_protect_client()
        result = await client.send_alarm_webhook(trigger_id)
        return format_protect_crud_result(result, "Alarm webhook sent")
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Protect API Tools — Users & Identity Users
# ---------------------------------------------------------------------------


@mcp.tool()
async def protect_list_users() -> str:
    """List all Protect users (filtered by access permissions)."""
    try:
        client = _get_protect_client()
        return format_protect_users(await client.list_users())
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_user(user_id: str) -> str:
    """Get detailed information about a specific Protect user.

    Args:
        user_id: The user ID.
    """
    try:
        client = _get_protect_client()
        return format_protect_device_detail(await client.get_user(user_id))
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_list_ulp_users() -> str:
    """List UniFi Identity (ULP) users with enrolled credentials (NFC, fingerprints)."""
    try:
        client = _get_protect_client()
        return format_protect_users(await client.list_ulp_users())
    except ProtectApiError as e:
        return _protect_error_response(e)


@mcp.tool()
async def protect_get_ulp_user(ulp_user_id: str) -> str:
    """Get detailed information about a specific UniFi Identity user.

    Args:
        ulp_user_id: The identity user ID.
    """
    try:
        client = _get_protect_client()
        return format_protect_device_detail(await client.get_ulp_user(ulp_user_id))
    except ProtectApiError as e:
        return _protect_error_response(e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Entry point for the MCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="UniFi MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to for SSE/HTTP transport (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for SSE/HTTP transport (default: 8000)",
    )
    args = parser.parse_args()

    mcp.settings.host = args.host
    mcp.settings.port = args.port

    # When binding to all interfaces, disable DNS rebinding protection
    # so reverse proxies with custom Host headers work correctly.
    if args.host == "0.0.0.0":
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
