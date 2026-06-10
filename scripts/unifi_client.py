#!/usr/bin/env python3
"""UniFi Network + Protect Integration API client (stdlib only, portable).

Config resolution order:
  1. $UNIFI_CONFIG (path to a JSON config file)
  2. $UNIFI_HOST + $UNIFI_API_KEY environment variables
  3. config.json found by walking up from this script's directory
  4. ~/.config/unifi/config.json

Config JSON: {"host": "https://192.168.1.1", "api_key": "...",
              "site_id": "<optional>", "verify_ssl": false}
"""
import json
import os
import ssl
import sys
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

NETWORK_BASE = "/proxy/network/integration/v1"
PROTECT_BASE = "/proxy/protect/integration/v1"


def load_config():
    p = os.environ.get("UNIFI_CONFIG")
    if p and Path(p).is_file():
        return json.loads(Path(p).read_text())
    if os.environ.get("UNIFI_HOST") and os.environ.get("UNIFI_API_KEY"):
        return {
            "host": os.environ["UNIFI_HOST"],
            "api_key": os.environ["UNIFI_API_KEY"],
            "site_id": os.environ.get("UNIFI_SITE_ID"),
            "verify_ssl": os.environ.get("UNIFI_VERIFY_SSL", "false").lower() == "true",
        }
    d = Path(__file__).resolve().parent
    for _ in range(5):
        c = d / "config.json"
        if c.is_file():
            return json.loads(c.read_text())
        d = d.parent
    cfg_dir = Path(os.environ.get("UNIFI_CONFIG_DIR", Path.home() / ".config" / "unifi"))
    c = cfg_dir / "config.json"
    if c.is_file():
        return json.loads(c.read_text())
    sys.exit("No UniFi config found. Run scripts/setup.py first, or set "
             "UNIFI_CONFIG, or UNIFI_HOST/UNIFI_API_KEY.")


class UnifiClient:
    def __init__(self, config=None):
        self.cfg = config or load_config()
        self.host = self.cfg["host"].rstrip("/")
        # UniFi consoles ship a self-signed certificate, so verification is
        # off by default. Set "verify_ssl": true if you've installed a real cert.
        self._ctx = ssl.create_default_context()
        if not self.cfg.get("verify_ssl", True):
            self._ctx.check_hostname = False
            self._ctx.verify_mode = ssl.CERT_NONE
        self._site_id = self.cfg.get("site_id")

    # ---------- low-level ----------
    def request(self, method, path, params=None, body=None, raw=False):
        """Make one API request. Returns parsed JSON, or raw bytes when
        raw=True (used for JPEG snapshots). Raises RuntimeError with the
        server's error detail on non-2xx responses."""
        url = self.host + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "X-API-KEY": self.cfg["api_key"],
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data else {}),
        })
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=30) as r:
                payload = r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {detail}") from None
        if raw:
            return payload
        return json.loads(payload) if payload.strip() else None

    def get(self, path, **params):
        return self.request("GET", path, params=params or None)

    def post(self, path, body=None):
        return self.request("POST", path, body=body)

    def patch(self, path, body=None):
        return self.request("PATCH", path, body=body)

    def paged(self, path, **params):
        """Iterate all items of a paginated Network API list endpoint.
        Network list responses look like {offset, limit, count, totalCount,
        data: [...]}; this walks every page transparently. (Protect endpoints
        return plain arrays and don't need this.)"""
        offset, limit = 0, int(params.pop("limit", 100))
        while True:
            page = self.get(path, offset=offset, limit=limit, **params)
            data = page.get("data", [])
            yield from data
            offset += len(data)
            if offset >= page.get("totalCount", 0) or not data:
                break

    # ---------- Network API ----------
    @property
    def site_id(self):
        """Site ID for Network API paths. Auto-discovered on first use —
        most home consoles have exactly one site, so we take the first."""
        if not self._site_id:
            self._site_id = self.get(f"{NETWORK_BASE}/sites")["data"][0]["id"]
        return self._site_id

    def _n(self, sub):
        return f"{NETWORK_BASE}/sites/{self.site_id}{sub}"

    def network_info(self):
        return self.get(f"{NETWORK_BASE}/info")

    def devices(self):
        return list(self.paged(self._n("/devices")))

    def device(self, device_id):
        return self.get(self._n(f"/devices/{device_id}"))

    def device_stats(self, device_id):
        return self.get(self._n(f"/devices/{device_id}/statistics/latest"))

    def device_restart(self, device_id):
        return self.post(self._n(f"/devices/{device_id}/actions"), {"action": "RESTART"})

    def port_power_cycle(self, device_id, port_idx):
        return self.post(self._n(f"/devices/{device_id}/interfaces/ports/{port_idx}/actions"),
                         {"action": "POWER_CYCLE"})

    def clients(self):
        return list(self.paged(self._n("/clients")))

    def client(self, client_id):
        return self.get(self._n(f"/clients/{client_id}"))

    def networks(self):
        return list(self.paged(self._n("/networks")))

    def wifi(self):
        return list(self.paged(self._n("/wifi/broadcasts")))

    def wans(self):
        return list(self.paged(self._n("/wans")))

    def acl_rules(self):
        return list(self.paged(self._n("/acl-rules")))

    def vouchers(self):
        return list(self.paged(self._n("/hotspot/vouchers")))

    def voucher_create(self, name, minutes=1440, count=1, **kw):
        body = {"name": name, "timeLimitMinutes": minutes, "count": count, **kw}
        return self.post(self._n("/hotspot/vouchers"), body)

    # ---------- Protect API ----------
    def protect_info(self):
        return self.get(f"{PROTECT_BASE}/meta/info")

    def cameras(self):
        return self.get(f"{PROTECT_BASE}/cameras")

    def camera(self, camera_id):
        return self.get(f"{PROTECT_BASE}/cameras/{camera_id}")

    def camera_by_name(self, name):
        for c in self.cameras():
            if c.get("name", "").lower() == name.lower():
                return c
        for c in self.cameras():
            if name.lower() in c.get("name", "").lower():
                return c
        raise RuntimeError(f"No camera matching '{name}'")

    def snapshot(self, camera_id, high_quality=True):
        return self.request("GET", f"{PROTECT_BASE}/cameras/{camera_id}/snapshot",
                            params={"highQuality": str(high_quality).lower()}, raw=True)

    def sensors(self):
        return self.get(f"{PROTECT_BASE}/sensors")

    def lights(self):
        return self.get(f"{PROTECT_BASE}/lights")

    def chimes(self):
        return self.get(f"{PROTECT_BASE}/chimes")

    def liveviews(self):
        return self.get(f"{PROTECT_BASE}/liveviews")

    def nvrs(self):
        return self.get(f"{PROTECT_BASE}/nvrs")

    def viewers(self):
        return self.get(f"{PROTECT_BASE}/viewers")

    def events_ws_url(self):
        """WebSocket URL for live Protect events (person/vehicle/package/etc.).
        Connect with header X-API-KEY. Requires a websocket library."""
        return self.host.replace("https://", "wss://") + f"{PROTECT_BASE}/subscribe/events"
