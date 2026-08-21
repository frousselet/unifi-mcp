"""Formatting helpers for UniFi Network API responses."""

import json
from typing import Any


def _pagination_hint(data: dict[str, Any]) -> str:
    total = data.get("totalCount")
    offset = data.get("offset", 0)
    count = len(data.get("data", []))
    if total is not None and offset + count < total:
        next_offset = offset + count
        return (
            f"\n---\n{count} of {total} shown. "
            f"Use offset={next_offset} to get the next page."
        )
    return ""


def _json_detail(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, default=str)


# --- Info & Sites ---


def format_network_info(data: dict[str, Any]) -> str:
    lines: list[str] = ["## Application Info\n"]
    for key, value in data.items():
        lines.append(f"- **{key}**: {value}")
    return "\n".join(lines)


def format_network_sites(data: dict[str, Any]) -> str:
    sites = data.get("data", [])
    if not sites:
        return "No sites found."

    lines: list[str] = [f"Found {len(sites)} site(s):\n"]
    for s in sites:
        name = s.get("name", "Unnamed")
        site_id = s.get("id", "N/A")
        ref = s.get("internalReference", "")
        lines.append(f"- **{name}** (ID: `{site_id}`)")
        if ref:
            lines.append(f"  Internal reference: {ref}")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


# --- Devices ---


def format_network_devices(data: dict[str, Any]) -> str:
    devices = data.get("data", [])
    if not devices:
        return "No devices found."

    lines: list[str] = [f"Found {len(devices)} device(s):\n"]
    for d in devices:
        name = d.get("name", "Unnamed")
        state = d.get("state", "unknown")
        lines.append(f"- **{name}** [{state}] (ID: `{d.get('id', 'N/A')}`)")
        lines.append(f"  Model: {d.get('model', 'N/A')}")
        lines.append(f"  IP: {d.get('ipAddress', 'N/A')} | MAC: {d.get('macAddress', 'N/A')}")
        lines.append(f"  Firmware: {d.get('firmwareVersion', 'N/A')} (updatable: {d.get('firmwareUpdatable', 'N/A')})")
        features = d.get("features", [])
        if features:
            lines.append(f"  Features: {', '.join(features)}")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_network_device_detail(data: dict[str, Any]) -> str:
    return _json_detail(data)


def format_network_device_statistics(data: dict[str, Any]) -> str:
    return _json_detail(data)


# --- Clients ---


def format_network_clients(data: dict[str, Any]) -> str:
    clients = data.get("data", [])
    if not clients:
        return "No connected clients found."

    lines: list[str] = [f"Found {len(clients)} client(s):\n"]
    for c in clients:
        name = c.get("name") or c.get("hostname") or c.get("macAddress", "Unknown")
        client_type = c.get("type", "N/A")
        lines.append(f"- **{name}** (ID: `{c.get('id', 'N/A')}`)")
        lines.append(f"  Type: {client_type}")
        ip = c.get("ipAddress")
        mac = c.get("macAddress")
        if ip:
            lines.append(f"  IP: {ip}")
        if mac:
            lines.append(f"  MAC: {mac}")
        connected = c.get("connectedAt")
        if connected:
            lines.append(f"  Connected at: {connected}")
        access = c.get("access", {})
        if access:
            lines.append(f"  Access: type={access.get('type', 'N/A')}, authorized={access.get('authorized', 'N/A')}")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_network_client_detail(data: dict[str, Any]) -> str:
    return _json_detail(data)


# --- Networks ---


def format_network_networks(data: dict[str, Any]) -> str:
    networks = data.get("data", [])
    if not networks:
        return "No networks found."

    lines: list[str] = [f"Found {len(networks)} network(s):\n"]
    for n in networks:
        name = n.get("name", "Unnamed")
        enabled = n.get("enabled", "N/A")
        vlan = n.get("vlanId", "N/A")
        lines.append(f"- **{name}** (ID: `{n.get('id', 'N/A')}`)")
        lines.append(f"  Enabled: {enabled} | VLAN: {vlan}")
        mgmt = n.get("management")
        if mgmt:
            lines.append(f"  Management: {mgmt}")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_network_network_detail(data: dict[str, Any]) -> str:
    return _json_detail(data)


# --- WiFi ---


def format_network_wifi(data: dict[str, Any]) -> str:
    broadcasts = data.get("data", [])
    if not broadcasts:
        return "No WiFi broadcasts found."

    lines: list[str] = [f"Found {len(broadcasts)} WiFi broadcast(s):\n"]
    for w in broadcasts:
        name = w.get("name", "Unnamed")
        enabled = w.get("enabled", "N/A")
        wifi_type = w.get("type", "N/A")
        lines.append(f"- **{name}** (ID: `{w.get('id', 'N/A')}`)")
        lines.append(f"  Type: {wifi_type} | Enabled: {enabled}")
        hidden = w.get("hideName", False)
        if hidden:
            lines.append("  Hidden SSID: yes")
        security = w.get("securityConfiguration", {})
        if security:
            lines.append(f"  Security: {security.get('protocol', 'N/A')}")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_network_wifi_detail(data: dict[str, Any]) -> str:
    return _json_detail(data)


# --- Firewall ---


def format_network_firewall_zones(data: dict[str, Any]) -> str:
    zones = data.get("data", [])
    if not zones:
        return "No firewall zones found."

    lines: list[str] = [f"Found {len(zones)} firewall zone(s):\n"]
    for z in zones:
        name = z.get("name", "Unnamed")
        lines.append(f"- **{name}** (ID: `{z.get('id', 'N/A')}`)")
        meta = z.get("metadata", {})
        if meta:
            lines.append(f"  Origin: {meta.get('origin', 'N/A')} | Configurable: {meta.get('configurable', 'N/A')}")
    lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_network_firewall_policies(data: dict[str, Any]) -> str:
    policies = data.get("data", [])
    if not policies:
        return "No firewall policies found."

    lines: list[str] = [f"Found {len(policies)} firewall policy(ies):\n"]
    for p in policies:
        name = p.get("name", "Unnamed")
        lines.append(f"- **{name}** (ID: `{p.get('id', 'N/A')}`)")
        src = p.get("source", {})
        dst = p.get("destination", {})
        if src or dst:
            lines.append(f"  Source zone: `{src.get('zoneId', 'N/A')}` -> Destination zone: `{dst.get('zoneId', 'N/A')}`")
    lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


# --- DNS ---


def format_network_dns_policies(data: dict[str, Any]) -> str:
    policies = data.get("data", [])
    if not policies:
        return "No DNS policies found."

    lines: list[str] = [f"Found {len(policies)} DNS policy(ies):\n"]
    for p in policies:
        name = p.get("name", "Unnamed")
        lines.append(f"- **{name}** (ID: `{p.get('id', 'N/A')}`)")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


# --- Vouchers ---


def format_network_vouchers(data: dict[str, Any]) -> str:
    vouchers = data.get("data", [])
    if not vouchers:
        return "No vouchers found."

    lines: list[str] = [f"Found {len(vouchers)} voucher(s):\n"]
    for v in vouchers:
        code = v.get("code", "N/A")
        lines.append(f"- **{code}** (ID: `{v.get('id', 'N/A')}`)")
        duration = v.get("duration")
        if duration:
            lines.append(f"  Duration: {duration} min")
        quota = v.get("quota")
        if quota:
            lines.append(f"  Quota: {quota}")
        used = v.get("used", 0)
        lines.append(f"  Used: {used}")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


# --- Supporting resources ---


def format_network_wans(data: dict[str, Any]) -> str:
    wans = data.get("data", [])
    if not wans:
        return "No WAN interfaces found."

    lines: list[str] = [f"Found {len(wans)} WAN interface(s):\n"]
    for w in wans:
        lines.append(f"- {json.dumps(w, default=str)}")
    lines.append("")
    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_network_vpn_tunnels(data: dict[str, Any]) -> str:
    tunnels = data.get("data", [])
    if not tunnels:
        return "No site-to-site VPN tunnels found."

    lines: list[str] = [f"Found {len(tunnels)} VPN tunnel(s):\n"]
    for t in tunnels:
        lines.append(f"- {json.dumps(t, default=str)}")
    lines.append("")
    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_network_vpn_servers(data: dict[str, Any]) -> str:
    servers = data.get("data", [])
    if not servers:
        return "No VPN servers found."

    lines: list[str] = [f"Found {len(servers)} VPN server(s):\n"]
    for s in servers:
        lines.append(f"- {json.dumps(s, default=str)}")
    lines.append("")
    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_network_radius_profiles(data: dict[str, Any]) -> str:
    profiles = data.get("data", [])
    if not profiles:
        return "No RADIUS profiles found."

    lines: list[str] = [f"Found {len(profiles)} RADIUS profile(s):\n"]
    for r in profiles:
        lines.append(f"- {json.dumps(r, default=str)}")
    lines.append("")
    lines.append(_pagination_hint(data))
    return "\n".join(lines)


# --- Pending devices & adoption ---


def format_network_pending_devices(data: dict[str, Any]) -> str:
    devices = data.get("data", [])
    if not devices:
        return "No devices pending adoption."

    lines: list[str] = [f"Found {len(devices)} device(s) pending adoption:\n"]
    for d in devices:
        lines.append(f"- **{d.get('model', 'Unknown')}** [{d.get('state', 'N/A')}]")
        lines.append(
            f"  MAC: {d.get('macAddress', 'N/A')} | IP: {d.get('ipAddress', 'N/A')}"
        )
        lines.append(
            f"  Firmware: {d.get('firmwareVersion', 'N/A')} | "
            f"Supported: {d.get('supported', 'N/A')}"
        )
        features = d.get("features", [])
        if features:
            lines.append(f"  Features: {', '.join(features)}")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


# --- ACL rules ---


def format_network_acl_rules(data: dict[str, Any]) -> str:
    rules = data.get("data", [])
    if not rules:
        return "No ACL rules found."

    lines: list[str] = [f"Found {len(rules)} ACL rule(s):\n"]
    for r in rules:
        name = r.get("name", "Unnamed")
        lines.append(f"- **{name}** (ID: `{r.get('id', 'N/A')}`)")
        lines.append(
            f"  Type: {r.get('type', 'N/A')} | Action: {r.get('action', 'N/A')} | "
            f"Enabled: {r.get('enabled', 'N/A')} | Index: {r.get('index', 'N/A')}"
        )
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


# --- Traffic matching lists ---


def format_network_traffic_matching_lists(data: dict[str, Any]) -> str:
    lists = data.get("data", [])
    if not lists:
        return "No traffic matching lists found."

    lines: list[str] = [f"Found {len(lists)} traffic matching list(s):\n"]
    for tml in lists:
        name = tml.get("name", "Unnamed")
        lines.append(f"- **{name}** (ID: `{tml.get('id', 'N/A')}`)")
        lines.append(f"  Type: {tml.get('type', 'N/A')}")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


# --- Switching ---


def _format_named_page(data: dict[str, Any], singular: str) -> str:
    items = data.get("data", [])
    if not items:
        return f"No {singular}s found."

    lines: list[str] = [f"Found {len(items)} {singular}(s):\n"]
    for it in items:
        name = it.get("name") or it.get("type", "Unnamed")
        lines.append(f"- **{name}** (ID: `{it.get('id', 'N/A')}`)")
        if it.get("type"):
            lines.append(f"  Type: {it['type']}")
        members = it.get("members")
        if isinstance(members, list):
            lines.append(f"  Members: {len(members)}")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_network_lags(data: dict[str, Any]) -> str:
    return _format_named_page(data, "LAG")


def format_network_mc_lag_domains(data: dict[str, Any]) -> str:
    return _format_named_page(data, "MC-LAG domain")


def format_network_switch_stacks(data: dict[str, Any]) -> str:
    return _format_named_page(data, "switch stack")


# --- Supporting resources (tags, countries, DPI) ---


def format_network_device_tags(data: dict[str, Any]) -> str:
    tags = data.get("data", [])
    if not tags:
        return "No device tags found."

    lines: list[str] = [f"Found {len(tags)} device tag(s):\n"]
    for t in tags:
        name = t.get("name", "Unnamed")
        device_ids = t.get("deviceIds", [])
        lines.append(f"- **{name}** (ID: `{t.get('id', 'N/A')}`)")
        lines.append(f"  Devices: {len(device_ids)}")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_network_countries(data: dict[str, Any]) -> str:
    countries = data.get("data", [])
    if not countries:
        return "No countries found."

    lines: list[str] = [f"Found {len(countries)} country(ies):\n"]
    for c in countries:
        lines.append(f"- {c.get('code', '??')}: {c.get('name', 'N/A')}")
    lines.append("")
    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_network_dpi(data: dict[str, Any], singular: str) -> str:
    items = data.get("data", [])
    if not items:
        return f"No DPI {singular}s found."

    lines: list[str] = [f"Found {len(items)} DPI {singular}(s):\n"]
    for it in items:
        lines.append(f"- `{it.get('id', 'N/A')}`: {it.get('name', 'N/A')}")
    lines.append("")
    lines.append(_pagination_hint(data))
    return "\n".join(lines)


# --- Generic detail ---


def format_network_detail(data: dict[str, Any]) -> str:
    """Render any single Network resource as pretty JSON."""
    return _json_detail(data)


# --- CRUD / Action results ---


def format_crud_result(data: dict[str, Any], action: str) -> str:
    if data.get("status") == "success":
        return f"{action} completed successfully."
    return _json_detail(data)


def format_action_result(data: dict[str, Any]) -> str:
    if data.get("status") == "success":
        return "Action executed successfully."
    return _json_detail(data)
