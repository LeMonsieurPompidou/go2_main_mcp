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
detects the single connected ASIX AX88179 USB Ethernet adapter and configures
it as `192.168.123.100/24` for the current session when run from an Administrator
PowerShell. Its Windows alias can change after replacing an adapter (for
example, `Ethernet 2` to `Ethernet 3`). With multiple connected ASIX adapters,
select one explicitly with `-AdapterName 'Ethernet 3'`; otherwise setup refuses
to choose. Setup also updates the robot-specific firewall rule to the selected
adapter and prints commands to restore DHCP.

### This Windows PC: WSL bridge and Docker web app

The verified robot address is `192.168.123.161`. Ubuntu-24.04 mirrors the ASIX
USB Ethernet adapter. Both WSL launchers find the interface with
`192.168.123.100` automatically; neither relies on a fixed `eth3` name.
An explicit `GO2_NETWORK_INTERFACE` override is validated against that address.
`scripts/Set-Go2DdsFirewall.ps1` adds Windows/WSL inbound UDP rules restricted
to that robot address; it includes commands to undo them.

The prepared runtime is at `/var/lib/go2-bridge-runtime/rootfs` inside Ubuntu.
It contains the tested `go2:bridge-fixed` image's existing Python, SDK and
dependencies, exported into a filesystem and run with `chroot` on WSL's native
network. The launcher drops the bridge to UID/GID 1000 after mounting `/dev`
and `/proc`. No second Docker daemon is required inside Ubuntu.

After restarting Windows or WSL, configure the USB adapter with the administrator
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

### Autonomous standing nod (ten minutes)

`go2_performance` runs a small stationary front-up/front-down nod using
`SportClient.Euler(0, pitch, 0)`. It does not walk or change whole-body height.
It uses the same exclusive control lock as the WSL bridge, so stop the bridge
before launching the performance. Only the moving robot may be connected to
the adapter's DDS network.

From PowerShell in this repository, preview the plan without loading the SDK
or connecting to a robot:

```powershell
& .\scripts\Start-Go2Performance.ps1 -DryRun -ClearanceCm 10
```

When the setup is ready, this command starts the physical movement in the
current terminal:

```powershell
& .\scripts\Start-Go2Performance.ps1 -ClearanceCm 10
```

There is a five-second countdown, then `StandUp`, five seconds for the robot
to settle, and `BalanceStand`. The timed performance then runs for 600 seconds
with a four-second nod period, default maximum pitch of +/-1.5 degrees, and
smooth two-second fades at the start and finish. Normal completion requests
neutral pitch and `StopMove`, leaving the robot standing. Joystick settings
are not changed and no joystick input is needed. This standalone process does
not expose the web app's STOP button; press **Ctrl+C in its terminal** to
cancel. Cancellation and cleanup can wait for an in-flight SDK call's
three-second timeout, so keep the robot's physical stop available.

The 10 cm clearance is the measured smallest gap in the starting standing
pose. Change it for a different setup, for example:

```powershell
& .\scripts\Start-Go2Performance.ps1 -ClearanceCm 8 -PitchDegrees 1 -PeriodSeconds 5
```

The planner reserves 5 cm, assumes torso points are within 75 cm of the pitch
centre, and reduces the amplitude if the remaining gap requires it. At the
default +/-1.5 degrees, the modelled point displacement is about 1.96 cm.
For the close-clearance setup, pitch is capped at 2 degrees, duration at 600 seconds, and a gap of
5 cm or less is rejected. This is a planning estimate, not measured collision
avoidance: balance corrections, body translation, legs and staging geometry
are not modelled. Keep the **whole initial stand-up transition clear**, and
rehearse with the robots separated before positioning them close together.
Any rejected SDK call aborts the routine without retrying the movement;
neutral-pose and stop failures are reported rather than hidden.

The normal default is ten minutes of nodding, in addition to the countdown and
standing preparation. `-DurationSeconds` can shorten the performance up to
that ten-minute maximum. `-Diagnostic` remains a short 16-second test at the
default nod period.

Built-in actions such as `Sit` and `StandUp` are firmware presets whose motion
amplitude is not exposed by the SDK. This routine uses `StandUp` to prepare
the robot and parameterized `Euler` pitch commands to construct the nodding
motion. SDK acknowledgements alone do not establish that the body follows;
the measured-pitch diagnostic below must be verified on the physical robot.

#### Larger test with the robots separated

For a rehearsal with the other robot and obstacles out of the motion area,
`-SeparatedTest` explicitly bypasses the clearance calculation and allows a
pitch command up to +/-15 degrees (ten times the original +/-1.5 command).
The normal close-clearance settings remain the default. Preview offline:

```powershell
& .\scripts\Start-Go2Performance.ps1 -SeparatedTest -PitchDegrees 15 -Diagnostic -DryRun
```

After reconnecting and running `Set-Go2Ethernet.ps1`, launch the 16-second test:

```powershell
& .\scripts\Start-Go2Performance.ps1 -SeparatedTest -PitchDegrees 15 -Diagnostic
```

The summary shows `clearance_limiter_enabled: false`; `-ClearanceCm` is unused
in this mode. The Euler pitch parameter reaches +/-0.262 radians, with the
same four-second cycle and two-second fades. Actual body tilt is measured:
the recorded small-command test had only about 9% of the commanded cyclic
amplitude, so a larger command still needs physical verification. There is
no automatic amplitude increase. The measured-pitch stop is the greater of
3 degrees and 1.2 times the selected command amplitude (18 degrees for this
15-degree test), relative to the initial measured pitch. Stale telemetry,
damping, rejected SDK calls and lost response still stop the routine.

Once the diagnostic and physical movement are satisfactory, the same separated
setup can run for ten minutes with:

```powershell
& .\scripts\Start-Go2Performance.ps1 -SeparatedTest -PitchDegrees 15 -DurationSeconds 600
```

Press Ctrl+C in the launching terminal to cancel and request neutral posture
and `StopMove`. Use the measured clearance setup again when positioning the
robots close together.

#### Diagnose accepted commands without visible movement

After reconnecting the robot and configuring the USB adapter, run one short
diagnostic before attempting the full presentation:

```powershell
& .\scripts\Start-Go2Performance.ps1 -ClearanceCm 10 -Diagnostic
```

With the default four-second period, this runs 16 seconds of nodding after
the usual countdown and standing preparation. Each update sends `Euler`
followed by `BalanceStand`, matching
[Unitree's standing-attitude example](https://support.unitree.com/home/en/developer/Motion_Services_Interface_V2.0).
The change still needs physical verification on the connected robot.

Both diagnostic and normal runs now require fresh `rt/sportmodestate`
telemetry before movement. The diagnostic prints commanded pitch, measured
IMU pitch and robot mode every second; normal runs also print every second
until response is confirmed, then every 15 seconds. The check excludes the
two-second startup fade, then uses two nod periods of measured pitch. If the
initial check is inconclusive, it allows one further period for the response
to settle (first check at 10 seconds, startup deadline at 14 seconds with the
default four-second period). Once confirmed, a failed response check aborts
immediately. Response detection removes linear settling drift, requires a
correlation of at least 0.60 and at least 0.150 degrees of fitted cyclic
peak-to-peak movement at the default command amplitude. For very small
commands, that minimum reduces to half the command amplitude with a 0.050
degree floor. It no longer assumes body tilt follows the command at a fixed
gain. The log reports measured range, required cyclic range, correlation,
command-to-body gain and sample count. Command and telemetry timestamps allow for up to one second of lag,
even when SDK calls make the actual update rate slower than the nominal 10 Hz.
Accepted commands without a measurable response abort with an explicit error.
Stale telemetry and damping mode also abort. A measured change exceeding
three degrees from the initial pitch aborts in the close-clearance setup;
the separated test uses the limit printed in its summary. These checks
measure attitude, not distance to the other robot.

Each live PowerShell launch saves a transcript in
`.runtime/performance-YYYYMMDD-HHMMSS.log` and a matching `.csv` containing
command/update times, telemetry age, commanded pitch, measured pitch and mode.
These traces distinguish a startup transient from a sustained but small
response, slow SDK calls, or motion that stops. A native Linux launch can
enable the same trace with `--trace-csv /path/to/trace.csv`.
Preview the diagnostic without connecting or moving:

```powershell
& .\scripts\Start-Go2Performance.ps1 -ClearanceCm 10 -Diagnostic -DryRun
```

On a native Linux installation with the Unitree SDK already installed:

```bash
GO2_NETWORK_INTERFACE=eno1 python -m go2_performance --clearance-cm 10
```

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
