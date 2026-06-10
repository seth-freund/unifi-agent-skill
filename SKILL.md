---
name: unifi
description: Manage a local UniFi system (Network + Protect) via Ubiquiti's official Integration APIs. Use for anything about the user's home/office network, WiFi, UniFi devices, switches, access points, network clients, who's online, device restarts, PoE ports, guest vouchers, security cameras, camera snapshots, doorbell, or smart detections (person/vehicle/package/animal). Can capture live camera snapshots as images for visual checks. Includes a setup command that discovers the user's system and builds an inventory.
homepage: https://github.com/seth-freund/unifi-agent-skill
metadata: {"openclaw": {"emoji": "📡", "requires": {"bins": ["python3"]}, "primaryEnv": "UNIFI_API_KEY"}}
---

# UniFi Network + Protect

Stdlib-only Python CLIs for a local UniFi console (UDM/UDM Pro/Cloud Gateway etc.).
The machine running these scripts must be able to reach the console on the LAN (or via VPN).

## First use — run setup

If `~/.config/unifi/config.json` (or `$UNIFI_CONFIG_DIR/config.json`) does not exist,
set up before anything else:

1. Ask the user for their console address (usually their gateway IP, e.g. `https://192.168.1.1`)
   and an API key (created in the UniFi console under **Settings → Control Plane → Integrations**).
   Treat the key as a secret — never print or log it.
2. Run: `python3 {baseDir}/scripts/setup.py --host <ADDRESS> --api-key <KEY>`
3. Setup validates both APIs, saves credentials (mode 600), and writes
   `inventory.md` + `inventory.json` to the config dir — a map of every device,
   VLAN, SSID, and camera with its smart-detect capabilities.

Read `~/.config/unifi/inventory.md` to learn the user's system before answering
questions about it. If devices/cameras seem missing or stale, refresh with
`python3 {baseDir}/scripts/setup.py --refresh`.

## Commands

Network (`python3 {baseDir}/scripts/network_cli.py ...`):
- `health` — offline devices, client counts, gateway CPU/RAM/uptime
- `devices` / `device <id>` / `stats <id>`
- `clients [--wired|--wireless] [--search TEXT]` — who's online (matches name/IP/MAC)
- `networks` / `wifi` / `wans` / `acl`
- `restart <id> --yes` / `cycle-port <device_id> <port_idx> --yes` — DESTRUCTIVE, confirm with the user first
- `vouchers` / `voucher-create <name> [--minutes N] [--count N]` — guest hotspot vouchers

Protect (`python3 {baseDir}/scripts/protect_cli.py ...`):
- `cameras` — list with state and smart-detect capabilities
- `camera <id-or-name>` — fuzzy name matching works ("doorbell", "driveway")
- `snapshot <id-or-name> -o /tmp/cam.jpg` — current JPEG; `snapshot --all DIR` for every camera
- `sensors | lights | chimes | liveviews | nvr | viewers`
- `watch [--types person,package]` — live smart-detect event stream (long-running websocket; needs `pip install websockets`)

Event-driven alerts (`python3 {baseDir}/scripts/webhook_relay.py`):
- Daemon that turns Protect Alarm Manager webhooks into OpenClaw agent wake-ups
  (`/hooks/agent`), enriched with the camera name and a trigger-time snapshot.
  Setup steps are in the script docstring and the repo README.
- If a wake-up message mentions a snapshot path, open and assess that image first,
  then decide whether the user needs to be notified.

## Conventions

- Visual questions ("is there a car in the driveway?", "any packages on the porch?"):
  snapshot the relevant camera to a temp file, view the image, answer from what you see.
- Prefer device/camera names over IDs when talking to the user.
- Briefing pattern (morning/evening check-ins): run `network_cli.py health`;
  flag devices offline or cameras not CONNECTED; mention clients that joined
  recently and aren't in the inventory; snapshot key exterior cameras and
  report anything visually out of place (unknown vehicles, open doors,
  packages). Keep the all-clear version to 2-3 sentences.
- Presence heuristic: the user's family phones appearing in `clients` output = someone is home.
- Destructive actions (restarts, port cycles) always need explicit user confirmation.
- Endpoint reference and known firmware limitations: `{baseDir}/reference/API.md`
