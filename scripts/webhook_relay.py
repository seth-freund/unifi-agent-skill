#!/usr/bin/env python3
"""UniFi Protect → OpenClaw webhook relay.

Turns Protect Alarm Manager webhooks into agent wake-ups: a package detection
or car arrival POSTs here, and this relay wakes your OpenClaw agent with an
enriched, actionable prompt — camera *name* (Alarm Manager only sends a MAC),
detection type, and a fresh snapshot the agent can open and look at.

    UniFi Protect Alarm Manager ──POST──▶ this relay ──POST──▶ OpenClaw /hooks/agent
                                            │ MAC → camera name (Protect API)
                                            │ snapshot → file the agent can view
                                            │ adds Bearer auth UniFi can't send

Why a relay instead of pointing UniFi straight at OpenClaw?
  1. OpenClaw hooks require an Authorization header; Alarm Manager's POST
     webhook cannot reliably attach one.
  2. The raw payload identifies cameras only by MAC — useless in a prompt.
  3. The relay grabs a snapshot at trigger time, so the agent sees what the
     camera saw, not a description of it.

Run:  python3 webhook_relay.py            (defaults to port 8666)
Test: curl -X POST http://localhost:8666/unifi-alarm -d '{"alarm":{...}}'

Config: ~/.config/unifi/relay.json (or $UNIFI_CONFIG_DIR/relay.json):
{
  "listen_port": 8666,
  "openclaw_url": "http://127.0.0.1:18789/hooks/agent",
  "openclaw_token": "YOUR_HOOKS_TOKEN",
  "snapshot_dir": "/tmp/unifi-alerts",
  "cooldown_sec": 90,
  "prompt_template": "optional custom prompt; {camera} {types} {time} {snapshot} {alarm} placeholders"
}

UniFi side (console → Protect → Alarm Manager):
  Add alarm → pick cameras + detection types (person/vehicle/package/...) →
  Action: Webhook → Custom Webhook → URL http://<this-host>:8666/unifi-alarm →
  Advanced Settings → method POST.

Keep this relay on your LAN only — do not port-forward it.
"""
import functools
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Unbuffered prints so logs appear immediately under systemd/launchd/nohup.
print = functools.partial(print, flush=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from unifi_client import UnifiClient  # noqa: E402

CONFIG_DIR = Path(os.environ.get("UNIFI_CONFIG_DIR", Path.home() / ".config" / "unifi"))

DEFAULT_PROMPT = (
    "UniFi alert '{alarm}': {types} detected on the {camera} camera at {time}. "
    "{snapshot_clause}Assess the situation and notify the user if it needs their "
    "attention (unknown person, package delivery, unexpected vehicle, etc.). "
    "If it's routine, log it and stay quiet."
)


def load_relay_config():
    p = CONFIG_DIR / "relay.json"
    cfg = json.loads(p.read_text()) if p.is_file() else {}
    cfg.setdefault("listen_port", int(os.environ.get("RELAY_PORT", 8666)))
    cfg.setdefault("openclaw_url", os.environ.get("OPENCLAW_HOOK_URL",
                                                  "http://127.0.0.1:18789/hooks/agent"))
    cfg.setdefault("openclaw_token", os.environ.get("OPENCLAW_HOOK_TOKEN", ""))
    cfg.setdefault("snapshot_dir", "/tmp/unifi-alerts")
    cfg.setdefault("cooldown_sec", 90)
    cfg.setdefault("prompt_template", DEFAULT_PROMPT)
    if not cfg["openclaw_token"]:
        sys.exit(f"No relay config found at {p}.\n"
                 "Run the guided setup first:  python3 setup.py --relay\n"
                 "(or set OPENCLAW_HOOK_URL / OPENCLAW_HOOK_TOKEN env vars)")
    return cfg


class Relay:
    """Holds shared state: camera MAC→info map, cooldown tracker, config."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.client = None          # lazy — relay still works if console is briefly down
        self._mac_map = {}          # "AABBCCDDEEFF" -> {"name":..., "id":...}
        self._mac_map_at = 0.0
        self._last_sent = {}        # (camera, types) -> monotonic ts, for cooldown
        self._lock = threading.Lock()

    # ---- camera enrichment -------------------------------------------------
    def _ensure_client(self):
        if self.client is None:
            self.client = UnifiClient()
        return self.client

    def mac_map(self):
        """MAC → camera info, cached 10 min. Protect sends bare MACs like
        '74ACB99F4E24'; we normalize by stripping separators and upcasing."""
        now = time.time()
        if now - self._mac_map_at > 600:
            try:
                cams = self._ensure_client().cameras()
                self._mac_map = {
                    str(c.get("mac", "")).replace(":", "").upper():
                        {"name": c.get("name", "unknown"), "id": c.get("id")}
                    for c in cams if c.get("mac")
                }
                self._mac_map_at = now
            except Exception as e:
                print(f"[relay] camera map refresh failed (continuing): {e}")
        return self._mac_map

    def snapshot(self, cam):
        """Best-effort snapshot to disk; returns path or None. Never raises —
        an alert without a snapshot still beats no alert."""
        try:
            data = self._ensure_client().snapshot(cam["id"])
            d = Path(self.cfg["snapshot_dir"])
            d.mkdir(parents=True, exist_ok=True)
            name = "".join(ch if ch.isalnum() else "_" for ch in cam["name"]).lower()
            p = d / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}.jpg"
            p.write_bytes(data)
            return str(p)
        except Exception as e:
            print(f"[relay] snapshot failed (continuing): {e}")
            return None

    # ---- the pipeline ------------------------------------------------------
    def handle_alarm(self, payload):
        """Alarm Manager POST body -> zero or more agent wake-ups."""
        alarm = payload.get("alarm", {})
        alarm_name = alarm.get("name", "UniFi alarm")
        ts = payload.get("timestamp")
        when = time.strftime("%I:%M %p", time.localtime(ts / 1000)) if ts else "just now"

        # Group trigger types per camera: one alert per camera, not per type.
        per_camera = {}
        for trig in alarm.get("triggers", []):
            mac = str(trig.get("device", "")).replace(":", "").upper()
            cam = self.mac_map().get(mac, {"name": f"camera {mac or 'unknown'}", "id": None})
            per_camera.setdefault(cam["name"], {"cam": cam, "types": []})
            per_camera[cam["name"]]["types"].append(trig.get("key", "motion"))

        if not per_camera:   # alarm with no triggers — still report it
            per_camera = {"(unspecified)": {"cam": {"name": "(unspecified)", "id": None},
                                            "types": ["motion"]}}

        sent = 0
        for cam_name, info in per_camera.items():
            types = ", ".join(sorted(set(info["types"])))
            key = (cam_name, types)
            with self._lock:   # cooldown: don't wake the agent for every frame
                now = time.monotonic()
                if now - self._last_sent.get(key, -1e9) < self.cfg["cooldown_sec"]:
                    print(f"[relay] cooldown, skipping {cam_name}/{types}")
                    continue
                self._last_sent[key] = now

            snap = self.snapshot(info["cam"]) if info["cam"].get("id") else None
            msg = self.cfg["prompt_template"].format(
                alarm=alarm_name, camera=cam_name, types=types, time=when,
                snapshot=snap or "(no snapshot)",
                snapshot_clause=f"A snapshot was saved to {snap} — open and review it. " if snap else "",
            )
            self.wake_agent(msg, f"UniFi: {cam_name}")
            sent += 1
        return sent

    def wake_agent(self, message, name):
        """POST to OpenClaw. /hooks/agent runs an isolated agent turn; if the
        configured URL ends in /hooks/wake it sends {text} instead."""
        url = self.cfg["openclaw_url"]
        body = ({"text": message, "mode": "now"} if url.rstrip("/").endswith("/wake")
                else {"message": message, "name": name})
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.cfg['openclaw_token']}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                print(f"[relay] woke agent ({r.status}): {message[:90]}...")
        except Exception as e:
            print(f"[relay] OpenClaw POST failed: {e}")


def make_handler(relay):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            if self.path.rstrip("/") != "/unifi-alarm":
                self.send_response(404); self.end_headers(); return
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                payload = json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            # Respond to UniFi immediately; enrich + forward in the background
            # so a slow snapshot can't make Alarm Manager think we're down.
            threading.Thread(target=relay.handle_alarm, args=(payload,), daemon=True).start()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def do_GET(self):   # Alarm Manager defaults to GET; accept it as a ping
            self.do_POST() if self.path.rstrip("/") == "/unifi-alarm" else (
                self.send_response(404), self.end_headers())

    return Handler


if __name__ == "__main__":
    cfg = load_relay_config()
    relay = Relay(cfg)
    print(f"[relay] listening on :{cfg['listen_port']} (POST /unifi-alarm)")
    print(f"[relay] forwarding to {cfg['openclaw_url']}")
    HTTPServer(("0.0.0.0", cfg["listen_port"]), make_handler(relay)).serve_forever()
