# UniFi MCP

An [MCP](https://modelcontextprotocol.io) server that lets Claude interact with your UniFi infrastructure. Supports the **Site Manager API** (cloud), the **Network API** (local console), and the **Protect API** (local console).

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

### Network API (local console)

Full CRUD access to a local UniFi console (UDM, UCG, etc.):

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
| **DNS**                             |                                      |
| `network_list_dns_policies`         | List DNS filtering policies          |
| **Vouchers**                        |                                      |
| `network_list_vouchers`             | List hotspot vouchers                |
| `network_create_vouchers`           | Create hotspot vouchers              |
| `network_delete_voucher`            | Delete a hotspot voucher             |
| **Supporting**                      |                                      |
| `network_list_wans`                 | List WAN interfaces                  |
| `network_list_vpn_tunnels`          | List site-to-site VPN tunnels        |
| `network_list_vpn_servers`          | List VPN servers                     |
| `network_list_radius_profiles`      | List RADIUS profiles                 |

### Protect API (local console)

Access to UniFi Protect cameras, sensors, and devices on a local console:

| Tool                              | Description                             |
| --------------------------------- | --------------------------------------- |
| **Info**                          |                                         |
| `protect_info`                    | Application info and NVR status         |
| **Cameras**                       |                                         |
| `protect_list_cameras`            | List all cameras                        |
| `protect_get_camera`              | Get camera details                      |
| `protect_update_camera`           | Update camera settings                  |
| `protect_get_camera_snapshot`     | Get a JPEG snapshot from a camera       |
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
| **Door Locks**                    |                                         |
| `protect_list_doorlocks`          | List all door locks                     |
| `protect_get_doorlock`            | Get door lock details                   |
| `protect_update_doorlock`         | Update door lock (lock/unlock, timeout) |
| **Events**                        |                                         |
| `protect_list_events`             | List recent events (motion, detections) |
| **Liveviews**                     |                                         |
| `protect_list_liveviews`          | List all liveviews                      |
| `protect_get_liveview`            | Get liveview details                    |
| `protect_create_liveview`         | Create a liveview                       |
| `protect_update_liveview`         | Update a liveview                       |
| **Viewers**                       |                                         |
| `protect_list_viewers`            | List all viewers (Viewport devices)     |
| `protect_get_viewer`              | Get viewer details                      |
| `protect_update_viewer`           | Update viewer settings                  |

## Prerequisites

- **UniFi API key** -- generate at [unifi.ui.com](https://unifi.ui.com) > API section. The same key works for Site Manager, Network, and Protect APIs.

## Quick start

### Docker (recommended)

```bash
# Build the image
docker build -t unifi-mcp .

# Run with Site Manager API only
docker run --rm -i -e UNIFI_API_KEY=your-key unifi-mcp

# Run with all three APIs (same key, just add the console host)
docker run --rm -i \
  -e UNIFI_API_KEY=your-key \
  -e UNIFI_NETWORK_HOST=192.168.1.1 \
  -e UNIFI_PROTECT_HOST=192.168.1.1 \
  unifi-mcp
```

### Docker Compose

```bash
cp .env.example .env
# Edit .env with your API keys
docker compose build
docker compose run --rm unifi-mcp
```

### Local (with uv)

```bash
# Install dependencies
uv sync

# Run the server
UNIFI_API_KEY=your-key uv run unifi-mcp
```

## Configuration

| Variable                    | Required | Default                 | Description                                          |
| --------------------------- | -------- | ----------------------- | ---------------------------------------------------- |
| `UNIFI_API_KEY`             | Yes      | --                      | UniFi API key (shared across all APIs)               |
| `UNIFI_API_BASE_URL`        | No       | `https://api.ui.com/v1` | Site Manager API base URL                            |
| `UNIFI_API_TIMEOUT`         | No       | `30`                    | HTTP timeout in seconds                              |
| `UNIFI_NETWORK_HOST`        | No       | --                      | Console IP/hostname for Network API                  |
| `UNIFI_NETWORK_API_KEY`     | No       | `UNIFI_API_KEY`         | Network API key (if different)                       |
| `UNIFI_NETWORK_VERIFY_SSL`  | No       | `false`                 | Verify SSL for Network API                           |
| `UNIFI_PROTECT_HOST`        | No       | --                      | Console IP/hostname for Protect API                  |
| `UNIFI_PROTECT_API_KEY`     | No       | `UNIFI_API_KEY`         | Protect API key (if different)                       |
| `UNIFI_PROTECT_VERIFY_SSL`  | No       | `false`                 | Verify SSL for Protect API                           |

The Network API tools are only available when `UNIFI_NETWORK_HOST` is set. The Protect API tools are only available when `UNIFI_PROTECT_HOST` is set. By default, `UNIFI_API_KEY` is used for all APIs. Set `UNIFI_NETWORK_API_KEY` or `UNIFI_PROTECT_API_KEY` if a console requires a separate key.

## Claude integration

### Claude Desktop (via mcp-remote)

Run the server with an HTTP transport, then connect Claude Desktop using [mcp-remote](https://www.npmjs.com/package/mcp-remote):

```bash
# Streamable HTTP (recommended)
docker compose up unifi-mcp-http

# Or SSE (legacy)
docker compose up unifi-mcp-sse

# Or without Compose
docker run --rm -p 8000:8000 \
  -e UNIFI_API_KEY=your-key \
  -e UNIFI_NETWORK_HOST=192.168.1.1 \
  -e UNIFI_PROTECT_HOST=192.168.1.1 \
  unifi-mcp --transport streamable-http
```

Add to your `claude_desktop_config.json`:

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

> For SSE transport, use `http://localhost:8000/sse` instead.

### Claude Desktop (stdio)

Alternatively, run the container directly via stdio:

```json
{
  "mcpServers": {
    "unifi": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "UNIFI_API_KEY=your-key",
        "-e", "UNIFI_NETWORK_HOST=192.168.1.1",
        "-e", "UNIFI_PROTECT_HOST=192.168.1.1",
        "unifi-mcp"
      ]
    }
  }
}
```

### Claude Code

Add to your MCP settings:

```json
{
  "mcpServers": {
    "unifi": {
      "command": "uv",
      "args": ["--directory", "/path/to/unifi-mcp", "run", "unifi-mcp"],
      "env": {
        "UNIFI_API_KEY": "your-key",
        "UNIFI_NETWORK_HOST": "192.168.1.1",
        "UNIFI_PROTECT_HOST": "192.168.1.1"
      }
    }
  }
}
```

## Project structure

```text
src/unifi_mcp/
  server.py               # MCP server and tool definitions
  client.py               # Site Manager API client
  formatting.py           # Site Manager response formatters
  network_client.py       # Network API client (local console)
  network_formatting.py   # Network response formatters
  protect_client.py       # Protect API client (local console)
  protect_formatting.py   # Protect response formatters
```

## License

MIT
