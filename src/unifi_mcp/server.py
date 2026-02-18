"""UniFi MCP Server -- exposes UniFi Site Manager and Network APIs as MCP tools."""

import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

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
from unifi_mcp.network_client import NetworkApiError, NetworkClient
from unifi_mcp.network_formatting import (
    format_action_result,
    format_crud_result,
    format_network_clients,
    format_network_client_detail,
    format_network_devices,
    format_network_device_detail,
    format_network_device_statistics,
    format_network_dns_policies,
    format_network_firewall_policies,
    format_network_firewall_zones,
    format_network_info,
    format_network_network_detail,
    format_network_networks,
    format_network_radius_profiles,
    format_network_sites,
    format_network_vouchers,
    format_network_vpn_servers,
    format_network_vpn_tunnels,
    format_network_wans,
    format_network_wifi,
    format_network_wifi_detail,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("unifi-mcp")


@dataclass
class AppContext:
    """Application context holding shared resources."""

    client: UniFiClient
    network_client: NetworkClient | None


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage API client lifecycles."""
    client = UniFiClient()
    logger.info("Site Manager API client initialized")

    network_client: NetworkClient | None = None
    if os.environ.get("UNIFI_NETWORK_HOST"):
        network_client = NetworkClient()
        logger.info(
            "Network API client initialized (host: %s)",
            os.environ["UNIFI_NETWORK_HOST"],
        )
    else:
        logger.info("Network API client not configured (UNIFI_NETWORK_HOST not set)")

    try:
        yield AppContext(client=client, network_client=network_client)
    finally:
        await client.close()
        if network_client:
            await network_client.close()
        logger.info("API clients closed")


mcp = FastMCP(
    "unifi",
    instructions=(
        "This server provides access to UniFi network infrastructure via two APIs:\n"
        "1. **Site Manager API** (cloud): list_hosts, get_host, list_sites, list_devices, "
        "get_isp_metrics, query_isp_metrics, get_sdwan_config\n"
        "2. **Network API** (local console): network_* tools for devices, clients, "
        "networks, WiFi, firewall, DNS, vouchers, and more\n\n"
        "Start with list_hosts or network_info to discover your infrastructure."
    ),
    lifespan=app_lifespan,
)


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


def _get_network_client() -> NetworkClient:
    """Get the Network API client from context, or raise a clear error."""
    client: NetworkClient | None = _get_app_context().network_client
    if client is None:
        raise NetworkApiError(
            0,
            "Network API not configured. Set UNIFI_NETWORK_HOST "
            "environment variable to your console IP/hostname.",
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
    client: UniFiClient = _get_app_context().client
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
    client: UniFiClient = _get_app_context().client
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
    client: UniFiClient = _get_app_context().client
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
    client: UniFiClient = _get_app_context().client
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
    client: UniFiClient = _get_app_context().client
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
    client: UniFiClient = _get_app_context().client
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
    client: UniFiClient = _get_app_context().client
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
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
