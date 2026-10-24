# Go2 ZMQ Bridge, CLI Client, Web App & MCP Server

A reusable interface layer for the Unitree Go2 quadruped robot. A ZeroMQ bridge process sits between the Unitree SDK and any number of clients, providing a clean JSON protocol for actions, movement, and camera streaming.

This independent repository preserves the history of
[gfadini/go2_main_mcp](https://github.com/gfadini/go2_main_mcp) and its source
project, [zhaw-physical-ai/go2_main](https://github.com/zhaw-physical-ai/go2_main),
with additional Windows/WSL connectivity fixes and web controller diagnostics.

## Architecture

```
┌─────────────┐   ZMQ REQ/REP    ┌──────────────────┐   Unitree SDK2   ┌──────────┐
│  CLI Client  │ ──────────────► │                  │ ───────────────► │          │
└─────────────┘   (port 5555)    │   go2_bridge     │                  │  Go2     │
                                 │                  │ ◄─────────────── │  Robot   │
┌─────────────┐   HTTP/WS        │  ┌─────────────┐ │                  │          │
│  Web App     │ ──────────────► │  │ cmd_handler  │ │                  └──────────┘
│  (FastAPI)   │ ◄── ZMQ SUB ── │  │ move_loop    │ │
└─────────────┘   (port 5556)    │  │ camera_pub   │ │
                                 │  └─────────────┘ │
┌─────────────┐   ZMQ REQ/REP   │                  │
│  MCP Server  │ ──────────────► │                  │
│  (stdio)     │ ◄── ZMQ SUB ── │                  │
└─────────────┘                  └──────────────────┘
```

**go2_bridge** runs three threads:

| Thread | Purpose | Rate |
|--------|---------|------|
| **command_handler** | ZMQ REQ/REP on port 5555 — dispatches action, move, stop, config commands | On demand |
| **movement_loop** | Relays last commanded velocity to the robot via SDK | 20 Hz |
| **camera_publisher** | Grabs JPEG frames from VideoClient, publishes on ZMQ PUB port 5556 | 10 FPS |

### Movement Safety

The movement loop continuously sends the last commanded velocity at 20 Hz. If no new `move` command arrives within **250 ms**, velocity automatically resets to zero. This gives smooth continuous motion from a joystick or keyboard while guaranteeing a quick stop if the client disconnects or crashes.

### Obstacle Avoidance

Enabled by default. Uses `ObstaclesAvoidClient` for all movement, routing through the robot's built-in obstacle detection. Can be toggled at runtime via the `obstacle_avoidance` command. Falls back to `SportClient.Move()` when disabled.

## Quick Start

### Prerequisites

- Python 3.11+ with the Unitree SDK2 Python package installed
- Network connection to the Go2 robot
- ZeroMQ, FastAPI, and uvicorn

### Option A: Docker (recommended)

```bash
cp .env.example .env
# edit GO2_NETWORK_INTERFACE for your machine (and GO2_NETWORK_ADDRESS too,
# if that interface has more than one IPv4 address — see Configuration below)

docker build -t go2 .

docker run --network host --env-file .env go2                 # bridge (default)
docker run --network host --env-file .env go2 webapp
docker run --network host --env-file .env go2 mcp
docker run --network host --env-file .env --rm go2 cli status
docker run --network host --env-file .env -it go2 bash        # shell
```

`--network host` is required — the bridge needs direct access to the host's network interface for DDS multicast discovery. With host networking, the bridge/webapp/CLI/MCP all share the host's loopback even when run as separate containers, so the defaults (`GO2_BRIDGE_HOST=localhost`) work unmodified.

The image builds CycloneDDS and the Unitree SDK from source (neither ships PyPI wheels) — see `Dockerfile` and `entrypoint.sh`.

On Docker Desktop, a web app using `-p 8081:8080` has its own network
namespace. To reach a bridge running with `--network host`, use the Docker
bridge gateway as `GO2_BRIDGE_HOST`. `host.docker.internal` points to the
Windows/macOS host and may not reach the bridge inside Docker's Linux VM.
For example, in PowerShell (after enabling Docker Desktop host networking):

```powershell
$go2Gateway = docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'
docker run --env-file .env -e "GO2_BRIDGE_HOST=$go2Gateway" -p 8081:8080 go2 webapp
```

Open http://localhost:8081. A successful `status: ok` confirms the web app
can reach the bridge; `Camera live` appears only when camera frames arrive.
The robot itself must still be reachable over DDS from the bridge's network.

Docker Desktop's host networking does not expose the Windows physical network
interfaces inside the Linux VM. The SDK bridge must run in an environment with
access to the robot's network (for example, a native Linux host connected to
the robot, or Ubuntu WSL with mirrored networking). See [Docker's host networking limitations](https://docs.docker.com/engine/network/drivers/host/#limitations)
and [WSL mirrored networking](https://learn.microsoft.com/windows/wsl/networking#mirrored-mode-networking).
For this PC's directly connected ASIX adapter, `scripts/Set-Go2Ethernet.ps1`
configures `Ethernet 2` as `192.168.123.100/24` for the current session when run
from an Administrator PowerShell. The script includes commands to restore DHCP.

### This Windows PC: WSL bridge and Docker web app

The verified robot address is `192.168.123.161`. Ubuntu-24.04 mirrors the ASIX
USB Ethernet adapter as `eth3`. The bridge runs there with
`GO2_NETWORK_INTERFACE=eth3` and `GO2_NETWORK_ADDRESS=192.168.123.100`.
`scripts/Set-Go2DdsFirewall.ps1` adds Windows/WSL inbound UDP rules restricted
to that robot address; it includes commands to undo them.

The prepared runtime is at `/var/lib/go2-bridge-runtime/rootfs` inside Ubuntu.
It contains the tested `go2:bridge-fixed` image's existing Python, SDK and
dependencies, exported into a filesystem and run with `chroot` on WSL's native
network. The launcher drops the bridge to UID/GID 1000 after mounting `/dev`
and `/proc`. No second Docker daemon is required inside Ubuntu.

After restarting Windows or WSL, configure Ethernet 2 with the administrator
script above, then start the bridge from this repository in PowerShell:

```powershell
& .\scripts\Start-Go2WslBridge.ps1
```

The hidden `wsl.exe` process keeps the bridge attached to WSL. A background
systemd service alone does not keep the WSL instance running. Bridge logs are
saved to `.runtime/bridge.stderr.log` and `.runtime/bridge.stdout.log`.
To stop the bridge gracefully:

```powershell
wsl -d Ubuntu-24.04 -u root --exec pkill -TERM -f '^/usr/local/bin/python -m go2_bridge$'
```

The `go2-webapp-fixed` Docker container uses
`GO2_BRIDGE_HOST=host.docker.internal` to reach this WSL bridge and publishes
the controller at http://localhost:8081. Keep a single bridge running.
`eno1` in the Linux examples below is a placeholder, not this PC's interface.

### Option B: Bare Metal

```bash
source go2_py311/bin/activate
pip install -r requirements_bridge.txt
```

### 1. Start the Bridge

```bash
GO2_NETWORK_INTERFACE=eno1 python -m go2_bridge
```

You should see:
```
Go2 Bridge running — CMD port 5555, PUB port 5556
```

### 2. CLI Client

```bash
# Check bridge status
python go2_client/cli_client.py status

# List available actions
python go2_client/cli_client.py list_actions

# Make the robot stand up
python go2_client/cli_client.py action stand_up

# Move forward at 0.3 m/s
python go2_client/cli_client.py move 0.3 0.0 0.0

# Emergency stop
python go2_client/cli_client.py stop

# Save a camera frame
python go2_client/cli_client.py camera_frame

# Toggle obstacle avoidance
python go2_client/cli_client.py obstacle_avoidance 0   # off
python go2_client/cli_client.py obstacle_avoidance 1   # on

# Set speed level (1-3)
python go2_client/cli_client.py speed_level 2
```

### 3. Web App

```bash
python -m go2_webapp
```

Open **http://localhost:8080** in a browser. The UI provides:

- **Live camera feed** via WebSocket
- **WASD + Q/E keyboard controls** for movement and rotation
- **On-screen directional buttons** (touch-friendly)
- **Action buttons** for all registered actions (stand up, sit, dance, flip, etc.)
- **Obstacle avoidance toggle**
- **Speed level selector** (1-3)
- **STOP button** (also spacebar)

### 4. MCP Server (for Claude Code / Claude Desktop)

The MCP server exposes robot control as tools that an LLM can call. It connects to the bridge as a ZMQ client, just like the CLI and web app.

```bash
# Run directly (stdio transport)
python -m go2_mcp

# Test with MCP inspector
mcp dev go2_mcp/server.py
```

**Available MCP tools:**

| Tool | Description |
|------|-------------|
| `get_status` | Get robot status (obstacle avoidance, speed, light) |
| `list_actions` | List all available actions |
| `execute_action` | Run a named action (stand_up, dance1, etc.) |
| `move` | Move with velocity (vx, vy, vyaw) |
| `stop` | Emergency stop |
| `set_obstacle_avoidance` | Toggle obstacle avoidance on/off |
| `set_speed_level` | Set speed 1-3 |
| `set_light` | Turn head light on/off |
| `get_camera_frame` | Capture and return a JPEG frame |

**Claude Desktop configuration** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "go2": {
      "command": "/path/to/go2/go2_py311/bin/python",
      "args": ["/path/to/go2/go2_mcp/server.py"]
    }
  }
}
```

**Claude Code configuration** (`.claude/settings.json` or project settings):
```json
{
  "mcpServers": {
    "go2": {
      "command": "/path/to/go2/go2_py311/bin/python",
      "args": ["-m", "go2_mcp"],
      "cwd": "/path/to/go2"
    }
  }
}
```

## ZMQ Protocol

### Commands (REQ/REP — port 5555)

All messages are JSON. Request format:

```json
{"cmd": "<command>", "params": {<optional params>}}
```

Response format:

```json
{"ok": true, "msg": "description", "data": null}
```

| Command | Params | Description |
|---------|--------|-------------|
| `action` | `{"name": "stand_up"}` | Execute a named action |
| `move` | `{"vx": 0.3, "vy": 0.0, "vyaw": 0.0}` | Set movement velocity |
| `stop` | — | Zero velocity immediately |
| `obstacle_avoidance` | `{"enabled": true}` | Toggle obstacle avoidance |
| `speed_level` | `{"level": 2}` | Set speed (1-3) |
| `light` | `{"on": true}` | Turn head light on/off |
| `list_actions` | — | Get list of available actions |
| `status` | — | Get current bridge status |

### Streams (PUB/SUB — port 5556)

| Topic | Payload | Rate |
|-------|---------|------|
| `camera` | Raw JPEG bytes | ~10 FPS |

Subscribe with topic filter `b"camera"`. Frames arrive as two-part multipart messages: `[topic, jpeg_data]`.

## Available Actions

| Action | Robot Behavior |
|--------|---------------|
| `stand_up` | Stand up from sitting/lying |
| `stand_down` | Lie down |
| `balance_stand` | Enter balance stand mode |
| `recovery_stand` | Recovery stand (from fallen) |
| `sit` | Sit down |
| `hello` | Wave hello |
| `stretch` | Stretching motion |
| `dance1` | Dance routine 1 |
| `dance2` | Dance routine 2 |
| `heart` | Heart gesture |
| `front_flip` | Front flip |
| `front_jump` | Front jump |
| `back_flip` | Back flip |
| `left_flip` | Left flip |
| `hand_stand` | Handstand |
| `damp` | Emergency soft stop (all motors) |
| `stop_move` | Stop current movement |

## Configuration

All settings via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `GO2_NETWORK_INTERFACE` | `eno1` | DDS network interface for SDK |
| `GO2_NETWORK_ADDRESS` | *(unset)* | Pin CycloneDDS to a specific IP on `GO2_NETWORK_INTERFACE`. Only needed if that interface has multiple IPv4 addresses (e.g. a shared test-bench NIC, one per robot) — CycloneDDS otherwise binds to whichever address it enumerates first, which may not be the robot's subnet, and DDS discovery fails silently (every SDK call hangs/times out with no error). |
| `GO2_ROBOT_IP` | *(unset)* | Reference only, not read by any code — DDS discovery is multicast-based. Handy for `ping`-ing the robot while troubleshooting `GO2_NETWORK_ADDRESS`/`GO2_NETWORK_INTERFACE`. |
| `GO2_ZMQ_CMD_PORT` | `5555` | REQ/REP command port |
| `GO2_ZMQ_PUB_PORT` | `5556` | PUB/SUB stream port |
| `GO2_MOVE_HZ` | `20` | Movement loop rate |
| `GO2_MOVE_TIMEOUT_MS` | `250` | Movement command timeout |
| `GO2_CAMERA_FPS` | `10` | Camera publish rate |
| `GO2_OBSTACLE_AVOIDANCE` | `1` | Enable obstacle avoidance at startup |
| `GO2_BRIDGE_HOST` | `localhost` | Bridge host (for clients) |
| `GO2_WEBAPP_HOST` | `0.0.0.0` | Web app bind address |
| `GO2_WEBAPP_PORT` | `8080` | Web app port |

## Writing Custom Clients

The bridge speaks plain JSON over ZeroMQ, so you can write clients in any language with a ZMQ binding:

```python
import zmq

ctx = zmq.Context()
sock = ctx.socket(zmq.REQ)
sock.connect("tcp://localhost:5555")

# Send a command
sock.send_json({"cmd": "action", "params": {"name": "hello"}})
response = sock.recv_json()
print(response)  # {"ok": true, "msg": "hello executed", "data": {"code": 0}}

# Subscribe to camera
sub = ctx.socket(zmq.SUB)
sub.connect("tcp://localhost:5556")
sub.subscribe(b"camera")
topic, jpeg_data = sub.recv_multipart()
with open("frame.jpg", "wb") as f:
    f.write(jpeg_data)
```

## Shutdown

Press `Ctrl+C` to stop the bridge. It will:
1. Zero all velocity commands
2. Call `UseRemoteCommandFromApi(False)` to restore normal robot control
3. Clean up ZMQ sockets
