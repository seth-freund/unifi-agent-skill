# unifi-agent-skill

An [AgentSkills](https://agentskills.io)-compatible skill that lets AI agents
(OpenClaw, Claude Code, Cowork, and friends) manage a local **UniFi** system —
both the **Network** application and **Protect** cameras — through Ubiquiti's
official Integration APIs.

Ask your agent things like:

- "What's my network health?" / "Who's on my WiFi right now?"
- "Show me the driveway camera" — the agent snapshots it and *looks at the image*,
  so "is there a car in the driveway?" and "any packages on the porch?" work too
- "Make a guest WiFi voucher for the weekend"
- "Restart the garage AP" / "Power-cycle the PoE port on that camera"
- "Watch for package detections" (live event stream)

**Zero pip dependencies** — pure Python 3 stdlib (optional `websockets` for the
live event watcher only).

## Requirements

- A UniFi OS console (UDM, UDM Pro/SE, Cloud Gateway, …) with Network 9+
  (Protect 5+ for cameras)
- An API key: UniFi console → **Settings → Control Plane → Integrations**
- The agent host on the same LAN as the console (or VPN'd in)
- Python 3.8+

## Install

### OpenClaw

```bash
openclaw skills install git:OWNER/unifi-agent-skill   # active workspace
openclaw skills install git:OWNER/unifi-agent-skill --global  # all agents
```

(Or clone into `~/.openclaw/skills/unifi` / `<workspace>/skills/unifi`.)

### Claude Code

```bash
git clone https://github.com/OWNER/unifi-agent-skill ~/.claude/skills/unifi
```

### Anywhere else

Any agent that reads AgentSkills `SKILL.md` folders: clone the repo into the
agent's skills directory.

## Setup (once)

```bash
python3 scripts/setup.py
```

Prompts for your console address and API key, validates both APIs, then writes
to `~/.config/unifi/` (override with `$UNIFI_CONFIG_DIR`):

- `config.json` — credentials, chmod 600
- `inventory.md` / `inventory.json` — a discovered map of your devices, VLANs,
  SSIDs, and cameras (with per-camera smart-detect capabilities) that the agent
  reads to understand *your* system

Or just ask your agent to set it up — the skill walks it through the same flow.
Re-run `python3 scripts/setup.py --refresh` after adding devices or cameras.

Credentials can alternatively come from env vars (`UNIFI_HOST` + `UNIFI_API_KEY`)
or a file pointed to by `$UNIFI_CONFIG` — handy for OpenClaw's
`skills.entries.unifi.env` injection.

## What's inside

| Path | Purpose |
|---|---|
| `SKILL.md` | agent instructions (AgentSkills format) |
| `scripts/setup.py` | credential validation + system discovery/inventory |
| `scripts/network_cli.py` | health, devices, clients, WiFi, vouchers, restarts |
| `scripts/protect_cli.py` | cameras, snapshots, sensors, live event watch |
| `scripts/unifi_client.py` | shared API client (import it for your own scripts) |
| `reference/API.md` | endpoint reference incl. known firmware limitations |

## Briefing recipes

These lines drop straight into a scheduled morning/evening briefing prompt
(OpenClaw cron job, Claude scheduled task, etc.):

- "Run the unifi skill's network health check and flag anything offline or unusual."
- "List any clients that joined the network in the last 12 hours that aren't in the inventory."
- "Confirm every Protect camera is CONNECTED; name any that aren't."
- "Snapshot the driveway, doorbell, and backyard cameras and report anything out of place —
  unknown vehicles, open doors, packages on the porch."
- "Evening check: are all family phones on WiFi? Snapshot exterior cameras for a visual all-clear."

The agent reads `~/.config/unifi/inventory.md` first, so it knows your camera
names and what each one can detect.

## Security notes

- The API key grants full read access to your cameras and network — treat it
  like a password. Setup stores it with mode 600 and the skill instructs agents
  never to print it.
- Nothing in this repo phones home; all traffic goes to your console.
- Destructive commands (`restart`, `cycle-port`) require a `--yes` flag, and the
  skill instructs agents to confirm with you first.

## Known API limitations (as of Network 10.4 / Protect 7.1)

The official Integration API cannot: block/unblock clients, edit firewall or
port-forwarding rules, or query historical Protect events over REST (live
websocket only). See `reference/API.md` for the full picture.

## License

MIT
