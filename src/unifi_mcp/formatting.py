"""Formatting helpers for UniFi API responses.

Each function takes a raw API response dict and returns a human-readable string.
"""

import json
from typing import Any


def _pagination_hint(data: dict[str, Any]) -> str:
    next_token = data.get("nextToken")
    if next_token:
        return f"\n---\nMore results available. Use next_token=\"{next_token}\" to get the next page."
    return ""


def format_hosts(data: dict[str, Any]) -> str:
    hosts = data.get("data", [])
    if not hosts:
        return "No hosts found."

    lines: list[str] = [f"Found {len(hosts)} host(s):\n"]
    for h in hosts:
        name = "Unknown"
        reported = h.get("reportedState") or {}
        if reported:
            name = reported.get("hostname") or reported.get("name") or "Unknown"
        lines.append(f"- **{name}** (ID: `{h.get('id', 'N/A')}`)")
        lines.append(f"  Type: {h.get('type', 'N/A')}")
        lines.append(f"  IP: {h.get('ipAddress', 'N/A')}")
        lines.append(f"  Owner: {h.get('owner', 'N/A')}")
        if reported:
            fw = reported.get("firmwareVersion") or reported.get("version")
            if fw:
                lines.append(f"  Firmware: {fw}")
            hw = reported.get("hardwareId") or reported.get("hardware", {}).get("shortname")
            if hw:
                lines.append(f"  Hardware: {hw}")
        state_change = h.get("lastConnectionStateChange")
        if state_change:
            lines.append(f"  Last connection change: {state_change}")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_host_detail(data: dict[str, Any]) -> str:
    host = data.get("data", data)
    return json.dumps(host, indent=2, default=str)


def format_sites(data: dict[str, Any]) -> str:
    sites = data.get("data", [])
    if not sites:
        return "No sites found."

    lines: list[str] = [f"Found {len(sites)} site(s):\n"]
    for s in sites:
        meta = s.get("meta", {})
        name = meta.get("name", "Unnamed")
        desc = meta.get("desc", "")
        tz = meta.get("timezone", "N/A")
        stats = s.get("statistics", {})
        device_count = stats.get("counts", {}).get("totalDevice", "N/A")
        client_count = stats.get("counts", {}).get("totalClient", "N/A")

        lines.append(f"- **{name}** (Site ID: `{s.get('siteId', 'N/A')}`)")
        if desc:
            lines.append(f"  Description: {desc}")
        lines.append(f"  Host ID: `{s.get('hostId', 'N/A')}`")
        lines.append(f"  Timezone: {tz}")
        lines.append(f"  Devices: {device_count} | Clients: {client_count}")
        lines.append(f"  Permission: {s.get('permission', 'N/A')} | Owner: {s.get('isOwner', 'N/A')}")

        isp_info = stats.get("isp", {})
        if isp_info:
            lines.append(f"  ISP: {isp_info.get('name', 'N/A')} (ASN: {isp_info.get('asn', 'N/A')})")
        lines.append("")

    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_devices(data: dict[str, Any]) -> str:
    host_groups = data.get("data", [])
    if not host_groups:
        return "No devices found."

    lines: list[str] = []
    total_devices = 0

    for group in host_groups:
        host_name = group.get("hostName", "Unknown Host")
        host_id = group.get("hostId", "N/A")
        devices = group.get("devices", [])
        total_devices += len(devices)

        lines.append(f"### {host_name} (`{host_id}`)")
        if not devices:
            lines.append("  No devices.\n")
            continue

        for d in devices:
            status = d.get("status", "unknown")
            status_icon = "online" if status == "online" else status
            lines.append(f"- **{d.get('name', 'Unnamed')}** [{status_icon}]")
            lines.append(f"  Model: {d.get('shortname', d.get('model', 'N/A'))} | Product: {d.get('productLine', 'N/A')}")
            lines.append(f"  IP: {d.get('ip', 'N/A')} | MAC: {d.get('mac', 'N/A')}")
            lines.append(f"  Firmware: {d.get('version', 'N/A')} (update: {d.get('firmwareStatus', 'N/A')})")
            if d.get("startupTime"):
                lines.append(f"  Uptime since: {d['startupTime']}")
            lines.append("")

    header = f"Found {total_devices} device(s) across {len(host_groups)} host(s):\n"
    lines.insert(0, header)
    lines.append(_pagination_hint(data))
    return "\n".join(lines)


def format_isp_metrics(data: dict[str, Any]) -> str:
    metrics_list = data.get("data", [])
    if not metrics_list:
        return "No ISP metrics found."

    lines: list[str] = []

    for entry in metrics_list:
        host_id = entry.get("hostId", "N/A")
        site_id = entry.get("siteId", "N/A")
        metric_type = entry.get("metricType", "N/A")
        periods = entry.get("periods", [])

        lines.append(f"### Site `{site_id}` (Host: `{host_id}`) - {metric_type} intervals")
        if not periods:
            lines.append("  No data points.\n")
            continue

        lines.append(f"  Data points: {len(periods)}")
        for p in periods:
            wan = p.get("data", {}).get("wan", {})
            ts = p.get("metricTime", "N/A")
            lines.append(f"  [{ts}]")
            lines.append(f"    Latency: avg={wan.get('avgLatency', 'N/A')}ms, max={wan.get('maxLatency', 'N/A')}ms")
            lines.append(f"    Bandwidth: down={wan.get('download_kbps', 'N/A')} kbps, up={wan.get('upload_kbps', 'N/A')} kbps")
            lines.append(f"    Uptime: {wan.get('uptime', 'N/A')}% | Packet loss: {wan.get('packetLoss', 'N/A')}%")
            isp = wan.get("ispName")
            if isp:
                lines.append(f"    ISP: {isp} (ASN: {wan.get('ispAsn', 'N/A')})")
        lines.append("")

    return "\n".join(lines)


def format_sdwan_configs(data: dict[str, Any]) -> str:
    configs = data.get("data", [])
    if not configs:
        return "No SD-WAN configurations found."

    lines: list[str] = [f"Found {len(configs)} SD-WAN configuration(s):\n"]
    for c in configs:
        lines.append(f"- **{c.get('name', 'Unnamed')}** (ID: `{c.get('id', 'N/A')}`)")
        lines.append(f"  Type: {c.get('type', 'N/A')}")
        lines.append("")

    return "\n".join(lines)


def format_sdwan_config_detail(data: dict[str, Any]) -> str:
    config = data.get("data", data)
    return json.dumps(config, indent=2, default=str)


def format_sdwan_config_status(data: dict[str, Any]) -> str:
    status = data.get("data", data)
    return json.dumps(status, indent=2, default=str)
