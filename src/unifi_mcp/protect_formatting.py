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


# --- Generic device lists ---


def _format_simple_devices(data: Any, singular: str, extra: Any = None) -> str:
    """Format a list of Protect devices sharing the id/name/state/modelKey shape.

    ``extra`` is an optional callable(item) -> list[str] of extra bullet lines.
    """
    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        return f"No {singular}s found."

    lines: list[str] = [f"Found {len(items)} {singular}(s):\n"]
    for it in items:
        name = it.get("name", "Unnamed")
        state = it.get("state", "unknown")
        lines.append(f"- **{name}** [{state}] (ID: `{it.get('id', 'N/A')}`)")
        model = it.get("modelKey") or it.get("type") or it.get("model")
        if model:
            lines.append(f"  Model: {model}")
        mac = it.get("mac")
        if mac:
            lines.append(f"  MAC: {mac}")
        if extra:
            lines.extend(f"  {line}" for line in extra(it))
        lines.append("")
    return "\n".join(lines)


def format_protect_sirens(data: Any) -> str:
    def extra(s: dict[str, Any]) -> list[str]:
        status = s.get("sirenStatus", {})
        return [f"Active: {status.get('isActive', 'N/A')} | Volume: {s.get('volume', 'N/A')}"]

    return _format_simple_devices(data, "siren", extra)


def format_protect_speakers(data: Any) -> str:
    def extra(s: dict[str, Any]) -> list[str]:
        st = s.get("speakerState", {})
        return [f"Status: {st.get('status', 'N/A')} | Volume: {s.get('volume', 'N/A')}"]

    return _format_simple_devices(data, "speaker", extra)


def format_protect_fobs(data: Any) -> str:
    def extra(f: dict[str, Any]) -> list[str]:
        return [f"Away state: {f.get('awayState', 'N/A')}"]

    return _format_simple_devices(data, "fob", extra)


def format_protect_relays(data: Any) -> str:
    def extra(r: dict[str, Any]) -> list[str]:
        outputs = r.get("outputs", [])
        states = ", ".join(
            f"#{o.get('id')}={o.get('state')}" for o in outputs
        )
        return [f"Outputs: {states}"] if states else []

    return _format_simple_devices(data, "relay", extra)


def format_protect_bridges(data: Any) -> str:
    def extra(b: dict[str, Any]) -> list[str]:
        clients = b.get("clients", [])
        return [f"Clients: {len(clients)}/{b.get('maxClients', 'N/A')}"]

    return _format_simple_devices(data, "bridge", extra)


def format_protect_link_stations(data: Any) -> str:
    def extra(ls: dict[str, Any]) -> list[str]:
        return [f"Alarm hub: {ls.get('isAlarmHub', 'N/A')}"]

    return _format_simple_devices(data, "link station", extra)


def format_protect_alarm_hubs(data: Any) -> str:
    def extra(h: dict[str, Any]) -> list[str]:
        hub = h.get("alarmHub", {})
        return [f"Armed: {hub.get('armed', 'N/A')}"] if hub else []

    return _format_simple_devices(data, "alarm hub", extra)


def format_protect_device_detail(data: dict[str, Any]) -> str:
    return _json_detail(data)


# --- Arm profiles ---


def format_protect_arm_profiles(data: Any) -> str:
    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        return "No arm profiles found."

    lines: list[str] = [f"Found {len(items)} arm profile(s):\n"]
    for p in items:
        lines.append(f"- **{p.get('name', 'Unnamed')}** (ID: `{p.get('id', 'N/A')}`)")
        lines.append(f"  Record everything: {p.get('recordEverything', 'N/A')}")
        lines.append(f"  Activation delay: {p.get('activationDelay', 'N/A')}ms")
        lines.append(f"  Schedules: {len(p.get('schedules', []))}")
        lines.append("")
    return "\n".join(lines)


# --- Users ---


def format_protect_users(data: Any) -> str:
    items = data if isinstance(data, list) else data.get("data", [])
    if not items:
        return "No users found."

    lines: list[str] = [f"Found {len(items)} user(s):\n"]
    for u in items:
        name = u.get("name") or u.get("fullName", "Unnamed")
        lines.append(f"- **{name}** (ID: `{u.get('id', 'N/A')}`)")
        email = u.get("email")
        if email:
            lines.append(f"  Email: {email}")
        status = u.get("status")
        if status:
            lines.append(f"  Status: {status}")
        ulp = u.get("ucoreUserId")
        if ulp:
            lines.append(f"  Identity user ID: `{ulp}`")
        lines.append("")
    return "\n".join(lines)


# --- CRUD result ---


def format_protect_crud_result(data: Any, action: str) -> str:
    if isinstance(data, dict) and data.get("status") == "success":
        return f"{action} completed successfully."
    return _json_detail(data)
