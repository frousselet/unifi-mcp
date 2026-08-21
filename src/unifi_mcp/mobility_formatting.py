"""Formatting helpers for UniFi Mobility API responses."""

import json
from typing import Any


def _json_detail(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _pagination_hint(data: dict[str, Any]) -> str:
    """Mobility collections echo total/offset/limit alongside data."""
    total = data.get("total")
    offset = data.get("offset", 0)
    count = len(data.get("data", []))
    if total is not None and offset + count < total:
        next_offset = offset + count
        return (
            f"\n---\n{count} of {total} shown. "
            f"Use offset={next_offset} to get the next page."
        )
    return ""


def _bytes_human(value: Any) -> str:
    """Render a byte count into a human-friendly string; -1 means unlimited."""
    if value is None:
        return "N/A"
    try:
        num = int(value)
    except (TypeError, ValueError):
        return str(value)
    if num < 0:
        return "unlimited"
    step = 1024.0
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < step:
            return f"{size:.1f} {unit}"
        size /= step
    return f"{size:.1f} PB"


# --- Workspaces ---


def format_mobility_workspaces(data: dict[str, Any]) -> str:
    workspaces = data.get("data", [])
    if not workspaces:
        return "No mobility workspaces found."

    lines: list[str] = [f"Found {len(workspaces)} workspace(s):\n"]
    for w in workspaces:
        name = w.get("workspace_name", "Unnamed")
        wid = w.get("workspace_id", "N/A")
        owner = "owner" if w.get("is_owner") else "member"
        lines.append(f"- **{name}** [{w.get('status', 'N/A')}, {owner}]")
        lines.append(f"  ID: `{wid}`")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_mobility_admins(data: dict[str, Any]) -> str:
    admins = data.get("data", [])
    if not admins:
        return "No workspace admins found."

    lines: list[str] = [f"Found {len(admins)} admin(s):\n"]
    for a in admins:
        name = a.get("name", "Unnamed")
        owner = " (owner)" if a.get("is_owner") else ""
        lines.append(f"- **{name}**{owner} [{a.get('status', 'N/A')}]")
        lines.append(f"  Email: {a.get('email', 'N/A')}")
        perms = a.get("permissions")
        if isinstance(perms, dict):
            lines.append(f"  Mobile Routing: {perms.get('umr', 'N/A')}")
        else:
            lines.append("  Permissions: none (no role binding)")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


# --- Devices ---


def format_mobility_devices(data: dict[str, Any]) -> str:
    devices = data.get("data", [])
    if not devices:
        return "No mobility devices found."

    lines: list[str] = [f"Found {len(devices)} device(s):\n"]
    for d in devices:
        name = d.get("name", "Unnamed")
        state = d.get("state", "unknown")
        lines.append(f"- **{name}** [{state}] (ID: `{d.get('id', 'N/A')}`)")
        lines.append(f"  Model: {d.get('model', 'N/A')}")
        lines.append(
            f"  Firmware: {d.get('firmware_version', 'N/A')} | "
            f"MAC: {d.get('mac_address') or 'N/A'}"
        )
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_mobility_device_detail(data: dict[str, Any]) -> str:
    device = data.get("data", data)
    if not isinstance(device, dict):
        return _json_detail(data)

    lines: list[str] = [f"## {device.get('name', 'Unnamed device')}\n"]
    lines.append(f"- **ID**: `{device.get('id', 'N/A')}`")
    lines.append(f"- **Model**: {device.get('model', 'N/A')}")
    lines.append(f"- **State**: {device.get('state', 'N/A')}")
    lines.append(f"- **Firmware**: {device.get('firmware_version', 'N/A')}")
    lines.append(f"- **MAC**: {device.get('mac_address') or 'N/A'}")
    lines.append(f"- **Mode**: {device.get('device_mode', 'N/A')}")

    lines.append("\n### WAN / Cellular")
    lines.append(f"- WAN source: {device.get('wan_source') or 'none'}")
    lines.append(f"- WAN IP: {device.get('wan_ip') or 'N/A'}")
    enabled = device.get("enabled_wans")
    if enabled:
        lines.append(f"- Enabled WANs (priority order): {', '.join(enabled)}")
    lines.append(f"- ISP: {device.get('isp') or 'N/A'}")
    lines.append(f"- LTE signal: {device.get('lte_signal_level') or 'N/A'}")
    lines.append(
        f"- Cellular data: {_bytes_human(device.get('cellular_data_usage_bytes'))} used"
        f" / {_bytes_human(device.get('cellular_data_limit_bytes'))} cap"
    )

    lines.append("\n### System")
    lines.append(f"- Memory usage: {device.get('memory_usage_percent', 'N/A')}%")
    lines.append(f"- Uptime: {device.get('uptime_seconds', 'N/A')}s")
    lines.append(f"- Clients: {device.get('client_count', 'N/A')}")
    lines.append(f"- LAN gateway: {device.get('host_address', 'N/A')}")
    lines.append(f"- PoE passthrough: {device.get('poe_passthrough', 'N/A')}")

    lines.append("\n### WiFi")
    lines.append(f"- Enabled: {device.get('wifi_enabled', 'N/A')}")
    lines.append(f"- SSID: {device.get('wifi_ssid') or 'N/A'}")
    lines.append(f"- TX power: {device.get('tx_power_level') or 'N/A'}")

    vpn_status = device.get("vpn_status")
    if device.get("vpn_profile_name") or vpn_status:
        lines.append("\n### VPN")
        lines.append(f"- Profile: {device.get('vpn_profile_name') or 'N/A'}")
        lines.append(f"- Status: {vpn_status or 'N/A'}")

    sub_plan = device.get("subscription_plan")
    if sub_plan or device.get("subscription_status"):
        lines.append("\n### Subscription")
        lines.append(f"- Plan: {sub_plan or 'none'}")
        lines.append(f"- Status: {device.get('subscription_status', 'N/A')}")

    for label, key in (
        ("Firewall rules", "firewall_rule_names"),
        ("Routing rules", "routing_rule_names"),
        ("DDNS profiles", "ddns_profile_names"),
    ):
        names = device.get(key)
        if names:
            lines.append(f"- {label}: {', '.join(names)}")

    location = device.get("location")
    if isinstance(location, dict):
        lines.append("\n### GPS Location")
        lines.append(
            f"- {location.get('latitude')}, {location.get('longitude')} "
            f"(updated: {location.get('last_updated')})"
        )

    return "\n".join(lines)


def format_mobility_device_clients(data: dict[str, Any]) -> str:
    clients = data.get("data", [])
    if not clients:
        return "No clients found on this device."

    lines: list[str] = [f"Found {len(clients)} client(s):\n"]
    for c in clients:
        name = c.get("name") or c.get("mac", "Unknown")
        status = c.get("connection_status", "N/A")
        ctype = c.get("type", "N/A")
        lines.append(f"- **{name}** [{status}, {ctype}]")
        lines.append(f"  MAC: {c.get('mac', 'N/A')} | IP: {c.get('ip_address') or 'N/A'}")
        if c.get("is_blocked"):
            lines.append("  Blocked: yes")
        exp = c.get("wifi_experience")
        if exp is not None:
            lines.append(f"  WiFi experience: {exp}/100")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


# --- Write results ---


def format_mobility_result(data: Any, action: str) -> str:
    if isinstance(data, dict) and data.get("status") == "success":
        return f"{action} completed successfully."
    return _json_detail(data)
