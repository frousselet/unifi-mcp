"""Formatting helpers for UniFi Protect API responses."""

import json
from typing import Any


def _json_detail(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


# --- App Info ---


def format_protect_app_info(data: dict[str, Any]) -> str:
    lines: list[str] = ["## Protect Application Info\n"]
    for key, value in data.items():
        lines.append(f"- **{key}**: {value}")
    return "\n".join(lines)


# --- NVR ---


def format_protect_nvr(data: Any) -> str:
    if isinstance(data, list):
        if not data:
            return "No NVR info found."
        nvr = data[0]
    else:
        nvr = data

    if not isinstance(nvr, dict):
        return _json_detail(data)

    lines: list[str] = ["## NVR System Info\n"]
    name = nvr.get("name", "Unnamed")
    lines.append(f"- **Name**: {name}")
    lines.append(f"- **ID**: `{nvr.get('id', 'N/A')}`")
    lines.append(f"- **Host**: {nvr.get('host', 'N/A')}")
    lines.append(f"- **Firmware**: {nvr.get('firmwareVersion', 'N/A')}")
    lines.append(f"- **Version**: {nvr.get('version', 'N/A')}")
    lines.append(f"- **Uptime**: {nvr.get('uptime', 'N/A')}")
    storage = nvr.get("storageInfo", {})
    if storage:
        lines.append(
            f"- **Storage**: {storage.get('usedSize', 'N/A')} / "
            f"{storage.get('totalSize', 'N/A')}"
        )
    return "\n".join(lines)


# --- Cameras ---


def format_protect_cameras(data: Any) -> str:
    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        return "No cameras found."

    lines: list[str] = [f"Found {len(items)} camera(s):\n"]
    for c in items:
        name = c.get("name", "Unnamed")
        state = c.get("state", "unknown")
        lines.append(f"- **{name}** [{state}] (ID: `{c.get('id', 'N/A')}`)")
        lines.append(f"  Model: {c.get('type', c.get('model', 'N/A'))}")
        lines.append(f"  IP: {c.get('host', 'N/A')}")
        lines.append(f"  Firmware: {c.get('firmwareVersion', 'N/A')}")
        lines.append(f"  Connected: {c.get('isConnected', 'N/A')}")
        lines.append(f"  Recording: {c.get('isRecording', 'N/A')}")
        lines.append("")

    return "\n".join(lines)


def format_protect_camera_detail(data: dict[str, Any]) -> str:
    return _json_detail(data)


# --- Lights ---


def format_protect_lights(data: Any) -> str:
    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        return "No lights found."

    lines: list[str] = [f"Found {len(items)} light(s):\n"]
    for light in items:
        name = light.get("name", "Unnamed")
        state = light.get("state", "unknown")
        lines.append(f"- **{name}** [{state}] (ID: `{light.get('id', 'N/A')}`)")
        lines.append(f"  Model: {light.get('type', light.get('model', 'N/A'))}")
        lines.append(f"  Motion detected: {light.get('isPirMotionDetected', 'N/A')}")
        lines.append("")

    return "\n".join(lines)


def format_protect_light_detail(data: dict[str, Any]) -> str:
    return _json_detail(data)


# --- Sensors ---


def format_protect_sensors(data: Any) -> str:
    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        return "No sensors found."

    lines: list[str] = [f"Found {len(items)} sensor(s):\n"]
    for s in items:
        name = s.get("name", "Unnamed")
        state = s.get("state", "unknown")
        lines.append(f"- **{name}** [{state}] (ID: `{s.get('id', 'N/A')}`)")
        lines.append(f"  Model: {s.get('type', s.get('model', 'N/A'))}")
        stats = s.get("stats", {})
        if stats:
            temp = stats.get("temperature", {}).get("value", "N/A")
            humidity = stats.get("humidity", {}).get("value", "N/A")
            light_val = stats.get("light", {}).get("value", "N/A")
            lines.append(f"  Temp: {temp} | Humidity: {humidity} | Light: {light_val}")
        lines.append("")

    return "\n".join(lines)


def format_protect_sensor_detail(data: dict[str, Any]) -> str:
    return _json_detail(data)


# --- Chimes ---


def format_protect_chimes(data: Any) -> str:
    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        return "No chimes found."

    lines: list[str] = [f"Found {len(items)} chime(s):\n"]
    for c in items:
        name = c.get("name", "Unnamed")
        state = c.get("state", "unknown")
        lines.append(f"- **{name}** [{state}] (ID: `{c.get('id', 'N/A')}`)")
        lines.append(f"  Model: {c.get('type', c.get('model', 'N/A'))}")
        lines.append("")

    return "\n".join(lines)


def format_protect_chime_detail(data: dict[str, Any]) -> str:
    return _json_detail(data)


# --- Door Locks ---


def format_protect_doorlocks(data: Any) -> str:
    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        return "No door locks found."

    lines: list[str] = [f"Found {len(items)} door lock(s):\n"]
    for d in items:
        name = d.get("name", "Unnamed")
        state = d.get("state", "unknown")
        lines.append(f"- **{name}** [{state}] (ID: `{d.get('id', 'N/A')}`)")
        lines.append(f"  Model: {d.get('type', d.get('model', 'N/A'))}")
        lines.append(f"  Lock status: {d.get('lockStatus', 'N/A')}")
        lines.append(f"  Auto-lock timeout: {d.get('autoLockTimeoutSec', 'N/A')}s")
        lines.append("")

    return "\n".join(lines)


def format_protect_doorlock_detail(data: dict[str, Any]) -> str:
    return _json_detail(data)


# --- Events ---


def format_protect_events(data: Any) -> str:
    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        return "No events found."

    lines: list[str] = [f"Found {len(items)} event(s):\n"]
    shown = items[:50]
    for e in shown:
        event_type = e.get("type", "unknown")
        start = e.get("start", "N/A")
        camera_id = e.get("cameraId", e.get("camera", "N/A"))
        lines.append(f"- [{start}] **{event_type}** (ID: `{e.get('id', 'N/A')}`)")
        if camera_id and camera_id != "N/A":
            lines.append(f"  Camera ID: `{camera_id}`")
        score = e.get("score")
        if score is not None:
            lines.append(f"  Score: {score}")
        lines.append("")

    if len(items) > 50:
        lines.append(
            f"\n---\nShowing 50 of {len(items)} events. "
            "The full list was truncated for readability."
        )

    return "\n".join(lines)


# --- Liveviews ---


def format_protect_liveviews(data: Any) -> str:
    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        return "No liveviews found."

    lines: list[str] = [f"Found {len(items)} liveview(s):\n"]
    for lv in items:
        name = lv.get("name", "Unnamed")
        lines.append(f"- **{name}** (ID: `{lv.get('id', 'N/A')}`)")
        is_default = lv.get("isDefault", False)
        if is_default:
            lines.append("  Default: yes")
        slots = lv.get("slots", [])
        lines.append(f"  Slots: {len(slots)}")
        lines.append("")

    return "\n".join(lines)


def format_protect_liveview_detail(data: dict[str, Any]) -> str:
    return _json_detail(data)


# --- Viewers ---


def format_protect_viewers(data: Any) -> str:
    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        return "No viewers found."

    lines: list[str] = [f"Found {len(items)} viewer(s):\n"]
    for v in items:
        name = v.get("name", "Unnamed")
        state = v.get("state", "unknown")
        lines.append(f"- **{name}** [{state}] (ID: `{v.get('id', 'N/A')}`)")
        lines.append(f"  Model: {v.get('type', v.get('model', 'N/A'))}")
        lines.append("")

    return "\n".join(lines)


def format_protect_viewer_detail(data: dict[str, Any]) -> str:
    return _json_detail(data)


# --- CRUD result ---


def format_protect_crud_result(data: Any, action: str) -> str:
    if isinstance(data, dict) and data.get("status") == "success":
        return f"{action} completed successfully."
    return _json_detail(data)
