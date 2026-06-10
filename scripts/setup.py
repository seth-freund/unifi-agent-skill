#!/usr/bin/env python3
"""UniFi skill setup: validate credentials, save config, and build an inventory
of the network and cameras so the agent knows what it's working with.

First-time setup (interactive):
  python3 setup.py

Non-interactive (good for agents):
  python3 setup.py --host https://192.168.1.1 --api-key KEY

Refresh inventory after network changes (uses saved config):
  python3 setup.py --refresh

Writes to --config-dir (default ~/.config/unifi/):
  config.json     credentials (chmod 600)
  inventory.md    human/agent-readable summary of the whole system
  inventory.json  same data, machine-readable

Get an API key: UniFi console -> Settings -> Control Plane -> Integrations.
"""
import argparse
import json
import os
import stat
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from unifi_client import UnifiClient  # noqa: E402

DEFAULT_DIR = Path(os.environ.get("UNIFI_CONFIG_DIR", Path.home() / ".config" / "unifi"))


def prompt_credentials(args):
    host = args.host or os.environ.get("UNIFI_HOST")
    key = args.api_key or os.environ.get("UNIFI_API_KEY")
    if not host:
        if not sys.stdin.isatty():
            sys.exit("Missing --host (or UNIFI_HOST). Example: --host https://192.168.1.1")
        host = input("UniFi console address [https://192.168.1.1]: ").strip() or "https://192.168.1.1"
    if not key:
        if not sys.stdin.isatty():
            sys.exit("Missing --api-key (or UNIFI_API_KEY). Create one in the UniFi "
                     "console under Control Plane -> Integrations.")
        import getpass
        key = getpass.getpass("API key (input hidden): ").strip()
    if not host.startswith("http"):
        host = "https://" + host
    return {"host": host.rstrip("/"), "api_key": key, "verify_ssl": args.verify_ssl}


def check(label, fn):
    try:
        result = fn()
        print(f"  ok  {label}")
        return result
    except Exception as e:
        print(f"  --  {label}: {e}")
        return None


def discover(c):
    """Probe both APIs and assemble an inventory dict. Missing apps are fine."""
    inv = {"generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"), "host": c.host}
    print("Probing Network API...")
    net_info = check("Network app", c.network_info)
    if net_info:
        inv["network"] = {
            "version": net_info.get("applicationVersion"),
            "siteId": c.site_id,
            "devices": [{"name": d.get("name"), "model": d.get("model"),
                         "ip": d.get("ipAddress"), "state": d.get("state"), "id": d.get("id")}
                        for d in (check("devices", c.devices) or [])],
            "vlans": [{"name": n.get("name"), "vlanId": n.get("vlanId"), "enabled": n.get("enabled")}
                      for n in (check("networks/VLANs", c.networks) or [])],
            "ssids": [{"name": w.get("name"), "enabled": w.get("enabled"),
                       "security": (w.get("securityConfiguration") or {}).get("type"),
                       "bandsGHz": w.get("broadcastingFrequenciesGHz")}
                      for w in (check("wifi SSIDs", c.wifi) or [])],
            "clientCount": len(check("clients", c.clients) or []),
        }
    print("Probing Protect API...")
    p_info = check("Protect app", c.protect_info)
    if p_info:
        cams = check("cameras", c.cameras) or []
        inv["protect"] = {
            "version": p_info.get("applicationVersion"),
            "cameras": [{"name": x.get("name"), "id": x.get("id"), "state": x.get("state"),
                         "smartDetect": (x.get("featureFlags") or {}).get("smartDetectTypes", [])}
                        for x in cams],
            "sensors": len(check("sensors", c.sensors) or []),
            "lights": len(check("lights", c.lights) or []),
            "chimes": len(check("chimes", c.chimes) or []),
        }
    if "network" not in inv and "protect" not in inv:
        sys.exit("\nNeither API responded. Check the address, the API key, and that "
                 "this machine can reach the console (same LAN/VPN).")
    return inv


def render_md(inv):
    L = [f"# UniFi System Inventory", "",
         f"Generated {inv['generatedAt']} from {inv['host']}. "
         f"Refresh with: `python3 setup.py --refresh`", ""]
    n = inv.get("network")
    if n:
        on = [d for d in n["devices"] if d["state"] == "ONLINE"]
        L += [f"## Network (v{n['version']}) — site `{n['siteId']}`", "",
              f"{len(n['devices'])} UniFi devices ({len(on)} online), "
              f"~{n['clientCount']} clients, {len(n['vlans'])} networks/VLANs, "
              f"{len(n['ssids'])} SSIDs", "", "### Devices", ""]
        L += [f"- {d['name']} — {d['model']}, {d['ip']}, {d['state']}, id `{d['id']}`"
              for d in n["devices"]]
        L += ["", "### Networks/VLANs", ""]
        L += [f"- {v['name']} (vlan {v['vlanId']}{'' if v['enabled'] else ', disabled'})"
              for v in n["vlans"]]
        L += ["", "### WiFi SSIDs", ""]
        L += [f"- {s['name']} — {s['security']}, bands {s['bandsGHz']}"
              f"{'' if s['enabled'] else ' (disabled)'}" for s in n["ssids"]]
        L += [""]
    p = inv.get("protect")
    if p:
        L += [f"## Protect (v{p['version']})", "",
              f"{len(p['cameras'])} cameras, {p['sensors']} sensors, "
              f"{p['lights']} lights, {p['chimes']} chimes", "", "### Cameras", ""]
        L += [f"- {c['name']} — {c['state']}, smart detect: "
              f"{', '.join(c['smartDetect']) or 'none'}, id `{c['id']}`"
              for c in p["cameras"]]
        L += [""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host")
    ap.add_argument("--api-key")
    ap.add_argument("--verify-ssl", action="store_true",
                    help="verify TLS (consoles use self-signed certs, so default is off)")
    ap.add_argument("--config-dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--refresh", action="store_true",
                    help="rebuild inventory using already-saved config")
    a = ap.parse_args()

    cfg_path = a.config_dir / "config.json"
    if a.refresh:
        if not cfg_path.is_file():
            sys.exit(f"No config at {cfg_path} — run setup without --refresh first.")
        cfg = json.loads(cfg_path.read_text())
    else:
        cfg = prompt_credentials(a)

    client = UnifiClient(cfg)
    inv = discover(client)

    a.config_dir.mkdir(parents=True, exist_ok=True)
    if not a.refresh:
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
        cfg_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        print(f"\nSaved credentials -> {cfg_path} (mode 600)")
    (a.config_dir / "inventory.json").write_text(json.dumps(inv, indent=2) + "\n")
    (a.config_dir / "inventory.md").write_text(render_md(inv))
    print(f"Saved inventory   -> {a.config_dir}/inventory.md (+ .json)")

    n, p = inv.get("network"), inv.get("protect")
    print("\nSetup complete:"
          + (f" {len(n['devices'])} devices, ~{n['clientCount']} clients;" if n else "")
          + (f" {len(p['cameras'])} cameras." if p else ""))


if __name__ == "__main__":
    main()
