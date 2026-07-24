# UniFi MCP

An [MCP](https://modelcontextprotocol.io) server that lets Claude interact with your UniFi infrastructure. Covers four UniFi APIs with **146 tools**:

- **Site Manager API** (cloud) — hosts, sites, devices, ISP metrics, SD-WAN.
- **Mobility API** (cloud) — UMR mobile routers: workspaces, admins, devices, clients, and device name/network/WiFi updates.
- **Network API** — devices, clients, networks, WiFi, firewall, ACL rules, DNS, switching, traffic-matching lists, vouchers, and more.
- **Protect API** — cameras (incl. PTZ, RTSPS, snapshots, talkback), lights, sensors, sirens, speakers, fobs, relays, bridges, link stations, alarm hubs, arm profiles, events, users.

The **Network** and **Protect** APIs can be reached either through the **cloud connector** (a single `unifi.ui.com` key proxied through `api.ui.com` — no LAN access needed) or by connecting **directly to a local console**. See [Reaching a console](#reaching-a-console).

## Features

### Site Manager API (cloud)

Read-only access to your UniFi account via `https://api.ui.com`:

| Tool                 | Description                                              |
| -------------------- | -------------------------------------------------------- |
| `list_hosts`         | List all consoles/gateways                               |
| `get_host`           | Get detailed host information                            |
| `list_sites`         | List all sites                                           |
| `list_devices`       | List all network devices                                 |
| `get_isp_metrics`    | Get ISP performance metrics (latency, bandwidth, uptime) |
| `query_isp_metrics`  | Query ISP metrics for specific sites                     |
| `get_sdwan_config`   | List or inspect SD-WAN configurations                    |

### Mobility API (cloud)

UniFi Mobile Router (UMR) management via `https://api.ui.com/v1/mobility` (requires the `mobility` scope on your key):

| Tool                              | Description                                        |
| --------------------------------- | -------------------------------------------------- |
| `mobility_list_workspaces`        | List mobility workspaces (cloud sites)             |
| `mobility_list_admins`            | List a workspace's admins and permissions          |
| `mobility_list_devices`           | List UMR devices in a workspace                    |
| `mobility_get_device`             | Full device detail (WAN, cellular, WiFi, VPN, GPS) |
| `mobility_list_device_clients`    | List clients connected to a device                 |
| `mobility_update_device_name`     | Rename a device (write scope, Admin)               |
| `mobility_update_device_network`  | Update LAN / DHCP settings (Admin)                 |
| `mobility_update_device_wireless` | Replace WiFi SSID + password (Admin)               |

### Network API

Full CRUD access to a UniFi console (UDM, UCG, etc.), via the cloud connector or a local connection:

| Tool                                | Description                          |
| ----------------------------------- | ------------------------------------ |
| **Info**                            |                                      |
| `network_info`                      | Application info and site discovery  |
| **Devices**                         |                                      |
| `network_list_devices`              | List all adopted devices             |
| `network_get_device`                | Get device details and statistics    |
| `network_device_action`             | Restart, locate, or adopt a device   |
| **Clients**                         |                                      |
| `network_list_clients`              | List all connected clients           |
| `network_get_client`                | Get client details                   |
| `network_client_action`             | Block or reconnect a client          |
| **Networks**                        |                                      |
| `network_list_networks`             | List configured networks (VLANs)     |
| `network_get_network`               | Get network details                  |
| `network_create_network`            | Create a network                     |
| `network_update_network`            | Update a network                     |
| `network_delete_network`            | Delete a network                     |
| **WiFi**                            |                                      |
| `network_list_wifi`                 | List WiFi broadcasts (SSIDs)         |
| `network_get_wifi`                  | Get WiFi broadcast details           |
| `network_create_wifi`               | Create a WiFi broadcast              |
| `network_update_wifi`               | Update a WiFi broadcast              |
| `network_delete_wifi`               | Delete a WiFi broadcast              |
| **Firewall**                        |                                      |
| `network_list_firewall_zones`       | List firewall zones                  |
| `network_list_firewall_policies`    | List firewall policies               |
| `network_create_firewall_policy`    | Create a firewall policy             |
| `network_update_firewall_policy`    | Update a firewall policy             |
| `network_delete_firewall_policy`    | Delete a firewall policy             |
| `network_get_firewall_policy`       | Get a firewall policy                |
| `network_get_firewall_zone` / `_create_` / `_update_` / `_delete_` | Firewall zone CRUD |
| `network_firewall_policy_ordering`  | Get/set firewall policy ordering     |
| **ACL rules**                       |                                      |
| `network_list_acl_rules` / `_get_` / `_create_` / `_update_` / `_delete_` | ACL rule CRUD |
| `network_acl_rule_ordering`         | Get/set ACL rule ordering            |
| **DNS**                             |                                      |
| `network_list_dns_policies` / `_get_` / `_create_` / `_update_` / `_delete_` | DNS policy CRUD |
| **Traffic matching lists**          |                                      |
| `network_list_traffic_matching_lists` / `_get_` / `_create_` / `_update_` / `_delete_` | IP/port list CRUD |
| **Switching**                       |                                      |
| `network_list_lags` / `network_get_lag` | Link Aggregation Groups          |
| `network_list_mc_lag_domains` / `network_get_mc_lag_domain` | MC-LAG domains |
| `network_list_switch_stacks` / `network_get_switch_stack` | Switch stacks    |
| **Adoption**                        |                                      |
| `network_list_pending_devices`      | List devices pending adoption        |
| `network_adopt_device`              | Adopt a device                       |
| `network_remove_device`             | Remove (unadopt) a device            |
| `network_port_action`               | Port action (e.g. PoE power-cycle)   |
| **Vouchers**                        |                                      |
| `network_list_vouchers`             | List hotspot vouchers                |
| `network_create_vouchers`           | Create hotspot vouchers              |
| `network_delete_voucher`            | Delete a hotspot voucher             |
| **Supporting**                      |                                      |
| `network_list_wans`                 | List WAN interfaces                  |
| `network_list_vpn_tunnels`          | List site-to-site VPN tunnels        |
| `network_list_vpn_servers`          | List VPN servers                     |
| `network_list_radius_profiles`      | List RADIUS profiles                 |
| `network_get_network_references`    | What references a network            |
| `network_list_device_tags`          | List device tags                     |
| `network_list_countries`            | List ISO country codes               |
| `network_list_dpi_applications`     | List DPI applications                |
| `network_list_dpi_categories`       | List DPI categories                  |

### Protect API

Access to UniFi Protect devices, via the cloud connector or a local connection:

| Tool                              | Description                             |
| --------------------------------- | --------------------------------------- |
| **Info**                          |                                         |
| `protect_info`                    | Application info and NVR status         |
| **Cameras**                       |                                         |
| `protect_list_cameras`            | List all cameras                        |
| `protect_get_camera`              | Get camera details                      |
| `protect_update_camera`           | Update camera settings                  |
| `protect_get_camera_snapshot`     | Get a JPEG snapshot from a camera       |
| `protect_camera_ptz_goto`         | Move a PTZ camera to a preset           |
| `protect_camera_ptz_patrol`       | Start/stop a PTZ patrol                 |
| `protect_camera_rtsps_streams`    | Get/create/delete RTSPS stream URLs     |
| `protect_camera_talkback_session` | Create a talkback session               |
| `protect_camera_disable_mic`      | Permanently disable the mic             |
| **Lights**                        |                                         |
| `protect_list_lights`             | List all lights                         |
| `protect_get_light`               | Get light details                       |
| `protect_update_light`            | Update light settings                   |
| **Sensors**                       |                                         |
| `protect_list_sensors`            | List all sensors                        |
| `protect_get_sensor`              | Get sensor details                      |
| `protect_update_sensor`           | Update sensor settings                  |
| **Chimes**                        |                                         |
| `protect_list_chimes`             | List all chimes                         |
| `protect_get_chime`               | Get chime details                       |
| `protect_update_chime`            | Update chime settings                   |
| **Sirens**                        |                                         |
| `protect_list_sirens` / `protect_get_siren` / `protect_update_siren` | Siren info & settings |
| `protect_siren_control`           | Play / stop / test a siren              |
| **Speakers**                      |                                         |
| `protect_list_speakers` / `protect_get_speaker` / `protect_update_speaker` | Speaker info & settings |
| `protect_test_speaker`            | Test speaker sound                      |
| **Fobs**                          |                                         |
| `protect_list_fobs` / `protect_get_fob` / `protect_update_fob` | Key fob info & settings |
| **Relays**                        |                                         |
| `protect_list_relays` / `protect_get_relay` / `protect_update_relay` | Relay info & settings |
| `protect_activate_relay_output`   | Control a relay output (on/off/pulse)   |
| **Bridges & Link Stations**       |                                         |
| `protect_list_bridges` / `protect_get_bridge` / `protect_update_bridge` | Bridge info & settings |
| `protect_list_link_stations` / `protect_get_link_station` / `protect_update_link_station` | Link station info & settings |
| **Alarm Hubs**                    |                                         |
| `protect_list_alarm_hubs` / `protect_get_alarm_hub` / `protect_update_alarm_hub` | Alarm hub info & settings |
| `protect_trigger_alarm_hub_output` | Trigger an alarm hub output            |
| **Arm Profiles & Alarm Manager**  |                                         |
| `protect_list_arm_profiles` / `_create_` / `_update_` / `_delete_` | Arm profile CRUD |
| `protect_arm_alarm`               | Enable/disable arm alarm, set profile   |
| `protect_send_alarm_webhook`      | Trigger alarms via webhook              |
| **Events**                        |                                         |
| `protect_list_events`             | List recent events (motion, detections) |
| **Liveviews**                     |                                         |
| `protect_list_liveviews` / `_get_` / `_create_` / `_update_` | Liveview info & CRUD |
| **Viewers**                       |                                         |
| `protect_list_viewers` / `protect_get_viewer` / `protect_update_viewer` | Viewer info & settings |
| **Users**                         |                                         |
| `protect_list_users` / `protect_get_user` | Protect users                   |
| `protect_list_ulp_users` / `protect_get_ulp_user` | UniFi Identity users     |

## Prerequisites

- **UniFi API key** — generate at [unifi.ui.com](https://unifi.ui.com) → API. Enable the **Site Manager** and **UniFi Applications** (Network, Protect) scopes; add **mobility** if you use UMR routers. The same key drives every API.

## Reaching a console

Site Manager and Mobility are always available (they are cloud APIs). The **Network** and **Protect** tools need to reach a specific console, in one of two ways:

- **Cloud connector (recommended).** Set `UNIFI_CONSOLE_ID` to the console (host) ID. Requests are proxied through `api.ui.com` with your `unifi.ui.com` key — nothing needs LAN access. Find the ID via the `list_hosts` tool (the `id` field, e.g. `900A6F…:123456789`).
- **Local console.** Set `UNIFI_NETWORK_HOST` / `UNIFI_PROTECT_HOST` to the console IP/hostname to connect directly over the LAN (self-signed certs, verification off by default).

If neither is configured for an application, its tools are simply not registered.

## Quick start

### Docker Compose (recommended — remote HTTP endpoint)

Runs the server as a streamable-HTTP service reachable from other machines:

```bash
cp .env.example .env          # set UNIFI_API_KEY and UNIFI_CONSOLE_ID
docker compose up -d --build
# MCP endpoint: http://<this-host>:8000/mcp
```

Put a TLS-terminating reverse proxy in front before exposing it publicly.

### Docker (one-off / stdio)

```bash
docker build -t unifi-mcp .

# Cloud connector: one key drives all four APIs
docker run --rm -i \
  -e UNIFI_API_KEY=your-key \
  -e UNIFI_CONSOLE_ID=900A6F...:123456789 \
  unifi-mcp
```

### Local (with uv)

```bash
uv sync
# stdio (default)
UNIFI_API_KEY=your-key UNIFI_CONSOLE_ID=... uv run unifi-mcp
# remote HTTP
UNIFI_API_KEY=your-key uv run unifi-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

## Configuration

| Variable                    | Required | Default                 | Description                                                  |
| --------------------------- | -------- | ----------------------- | ------------------------------------------------------------ |
| `UNIFI_API_KEY`             | Yes      | —                       | UniFi cloud API key (shared across all APIs)                 |
| `UNIFI_API_BASE_URL`        | No       | `https://api.ui.com/v1` | Site Manager API base URL                                    |
| `UNIFI_API_TIMEOUT`         | No       | `30`                    | HTTP timeout in seconds                                      |
| `UNIFI_CONSOLE_ID`          | No       | —                       | Console (host) ID for Network + Protect via the cloud connector |
| `UNIFI_NETWORK_CONSOLE_ID`  | No       | `UNIFI_CONSOLE_ID`      | Console ID override for Network only                         |
| `UNIFI_PROTECT_CONSOLE_ID`  | No       | `UNIFI_CONSOLE_ID`      | Console ID override for Protect only                         |
| `UNIFI_NETWORK_HOST`        | No       | —                       | Local console IP/hostname for Network (instead of console ID) |
| `UNIFI_PROTECT_HOST`        | No       | —                       | Local console IP/hostname for Protect (instead of console ID) |
| `UNIFI_NETWORK_VERIFY_SSL`  | No       | `false`                 | Verify SSL for a local Network console                       |
| `UNIFI_PROTECT_VERIFY_SSL`  | No       | `false`                 | Verify SSL for a local Protect console                       |
| `UNIFI_MOBILITY_API_KEY`    | No       | `UNIFI_API_KEY`         | Mobility API key (if different)                              |
| `UNIFI_NETWORK_API_KEY`     | No       | `UNIFI_API_KEY`         | Network API key (if different)                               |
| `UNIFI_PROTECT_API_KEY`     | No       | `UNIFI_API_KEY`         | Protect API key (if different)                               |
| `MCP_PORT`                  | No       | `8000`                  | Host port the HTTP endpoint is published on (compose)        |

When both a local host and a console ID are set for an application, **local mode wins**. By default `UNIFI_API_KEY` is used everywhere; set a per-API key only if a console needs a different one.

## Multi-tenant onboarding (self-service SaaS mode)

Instead of one set of credentials, you can run a hosted service where **each user registers their own UniFi key through a web page** and receives an MCP URL + OAuth client id/secret to paste into Claude's custom-connector dialog.

```bash
cp .env.example .env
# set at least:
#   UNIFI_PUBLIC_URL=https://unifi.example.com   (HTTPS in production)
#   UNIFI_SECRET_KEY=<Fernet key>                (see below)
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"  # -> UNIFI_SECRET_KEY

docker compose --profile multitenant up -d --build
```

This serves, on one port:

| Path | Purpose |
| ---- | ------- |
| `GET /setup` | First-run: register the first admin **passkey** |
| `GET /login` | Sign in with a passkey |
| `GET /` | Onboarding form (admin only) |
| `POST /onboard` | Creates a tenant → returns MCP URL + OAuth `client_id` / `client_secret` |
| `GET /admin` | List / delete tenant connections |
| `/mcp` | The shared, OAuth-protected MCP endpoint |
| `/authorize`, `/token`, `/.well-known/oauth-*` | OAuth 2.1 authorization server |

**Admin auth is passwordless (WebAuthn passkeys only).** There is no default account: the first visit invites you to create one (Touch ID / Windows Hello / security key / phone). Add more passkeys later from the admin area.

**How tenant auth works:** each tenant gets a confidential OAuth client. Claude runs the authorization-code + PKCE flow with the issued id/secret and receives an access token bound to that tenant; tool calls resolve the tenant's UniFi credentials from the token.

**Data at rest:** stored in a JSON file (`UNIFI_TENANT_STORE`, on the `unifi-tenants` volume). Secrets are protected:
- UniFi API keys and OAuth client secrets are **encrypted** with Fernet (`UNIFI_SECRET_KEY`).
- OAuth access/refresh tokens and authorization codes are stored **hashed** (SHA-256) — the raw bearer secrets are never written to disk.
- Passkey public keys and console IDs are stored as non-secret metadata.

**Security notes:**
- Passkeys **require HTTPS** (except on `localhost`) and bind to `UNIFI_PUBLIC_URL`'s hostname — set it to the real public origin and terminate TLS in front.
- Onboarding is admin-gated; optionally also set `UNIFI_ONBOARD_CODE`.
- Redirect URIs are restricted to Claude's web callbacks by default; override with `UNIFI_OAUTH_REDIRECT_URIS`.
- Keep `UNIFI_SECRET_KEY` stable and backed up, or stored tenant data becomes unreadable.

Configuration variables for this mode: `UNIFI_MULTITENANT`, `UNIFI_PUBLIC_URL`, `UNIFI_SECRET_KEY`, `UNIFI_TENANT_STORE`, `UNIFI_RP_NAME`, `UNIFI_ONBOARD_CODE`, `UNIFI_OAUTH_REDIRECT_URIS` (see `.env.example`).

## Claude integration

### Remote connector (no local config file)

Run the HTTP endpoint (`docker compose up -d`), expose it (ideally behind HTTPS), then in Claude add a **custom connector**: paste the MCP server URL `https://<your-host>/mcp`. For the single-tenant server no OAuth is needed; for the [multi-tenant service](#multi-tenant-onboarding-self-service-saas-mode) paste the `client_id`/`client_secret` from onboarding into the connector's OAuth fields.

### Claude Desktop (via mcp-remote)

To bridge the remote endpoint into Claude Desktop's config instead:

```json
{
  "mcpServers": {
    "unifi": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:8000/mcp"]
    }
  }
}
```

### Claude Desktop / Claude Code (stdio)

Run the container or `uv` directly over stdio:

```json
{
  "mcpServers": {
    "unifi": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "UNIFI_API_KEY=your-key",
        "-e", "UNIFI_CONSOLE_ID=900A6F...:123456789",
        "unifi-mcp"
      ]
    }
  }
}
```

## Project structure

```text
src/unifi_mcp/
  server.py               # MCP server and tool definitions (143 tools)
  client.py               # Site Manager API client (cloud)
  formatting.py           # Site Manager response formatters
  mobility_client.py      # Mobility API client (cloud)
  mobility_formatting.py  # Mobility response formatters
  network_client.py       # Network API client (cloud connector or local)
  network_formatting.py   # Network response formatters
  protect_client.py       # Protect API client (cloud connector or local)
  protect_formatting.py   # Protect response formatters
  tenant.py               # Multi-tenant: encrypted store, client bundles, registry
  oauth.py                # Multi-tenant: OAuth 2.1 authorization-server provider
  web.py                  # Multi-tenant: onboarding UI + combined ASGI app
```

## License

MIT
