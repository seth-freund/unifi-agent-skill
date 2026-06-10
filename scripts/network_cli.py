#!/usr/bin/env python3
"""UniFi Network CLI.

Usage:
  network_cli.py devices [--json]
  network_cli.py device <id>
  network_cli.py stats <id>
  network_cli.py restart <id> [--yes]
  network_cli.py cycle-port <device_id> <port_idx> [--yes]
  network_cli.py clients [--wired|--wireless] [--search TEXT] [--json]
  network_cli.py networks
  network_cli.py wifi
  network_cli.py wans
  network_cli.py acl
  network_cli.py vouchers
  network_cli.py voucher-create <name> [--minutes N] [--count N]
  network_cli.py health
"""
import argparse
import json
import sys
from unifi_client import UnifiClient


def jprint(obj):
    print(json.dumps(obj, indent=2, default=str))


def table(rows, cols):
    """Print dicts as an aligned plain-text table (no dependencies)."""
    if not rows:
        print("(none)")
        return
    widths = [max(len(str(r.get(c, "") or "")) for r in rows + [{c: c}]) for c in cols]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    for r in rows:
        print("  ".join(str(r.get(c, "") or "").ljust(w) for c, w in zip(cols, widths)))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--wired", action="store_true")
    ap.add_argument("--wireless", action="store_true")
    ap.add_argument("--search")
    ap.add_argument("--minutes", type=int, default=1440)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    c = UnifiClient()

    if a.cmd == "devices":
        d = c.devices()
        if a.json:
            jprint(d)
        else:
            table([{"name": x.get("name"), "model": x.get("model"), "ip": x.get("ipAddress"),
                    "state": x.get("state"), "id": x.get("id")} for x in d],
                  ["name", "model", "ip", "state", "id"])
    elif a.cmd == "device":
        jprint(c.device(a.args[0]))
    elif a.cmd == "stats":
        jprint(c.device_stats(a.args[0]))
    elif a.cmd == "restart":
        if not a.yes:
            sys.exit("Add --yes to confirm device restart.")
        jprint(c.device_restart(a.args[0]) or {"ok": True})
    elif a.cmd == "cycle-port":
        if not a.yes:
            sys.exit("Add --yes to confirm PoE port power cycle.")
        jprint(c.port_power_cycle(a.args[0], a.args[1]) or {"ok": True})
    elif a.cmd == "clients":
        cl = c.clients()
        if a.wired:
            cl = [x for x in cl if x.get("type") == "WIRED"]
        if a.wireless:
            cl = [x for x in cl if x.get("type") == "WIRELESS"]
        if a.search:
            s = a.search.lower()
            cl = [x for x in cl if s in json.dumps(x).lower()]
        if a.json:
            jprint(cl)
        else:
            table([{"name": x.get("name"), "ip": x.get("ipAddress"), "mac": x.get("macAddress"),
                    "type": x.get("type"), "connected": x.get("connectedAt")} for x in cl],
                  ["name", "ip", "mac", "type", "connected"])
            print(f"\n{len(cl)} clients")
    elif a.cmd == "networks":
        table([{"name": x.get("name"), "vlan": x.get("vlanId"), "enabled": x.get("enabled"),
                "id": x.get("id")} for x in c.networks()], ["name", "vlan", "enabled", "id"])
    elif a.cmd == "wifi":
        table([{"ssid": x.get("name"), "enabled": x.get("enabled"),
                "security": (x.get("securityConfiguration") or {}).get("type"),
                "bands": ",".join(map(str, x.get("broadcastingFrequenciesGHz", [])))}
               for x in c.wifi()], ["ssid", "enabled", "security", "bands"])
    elif a.cmd == "wans":
        jprint(c.wans())
    elif a.cmd == "acl":
        jprint(c.acl_rules())
    elif a.cmd == "vouchers":
        jprint(c.vouchers())
    elif a.cmd == "voucher-create":
        jprint(c.voucher_create(a.args[0], minutes=a.minutes, count=a.count))
    elif a.cmd == "health":
        # One-shot summary designed for daily briefings: device states,
        # client counts, and the gateway's vitals (CPU/RAM/uptime).
        devs = c.devices()
        offline = [d for d in devs if d.get("state") != "ONLINE"]
        gw = next((d for d in devs if "Dream Machine" in (d.get("model") or "")), devs[0])
        stats = c.device_stats(gw["id"])
        cl = c.clients()
        print(f"Devices: {len(devs)} total, {len(offline)} offline")
        for d in offline:
            print(f"  OFFLINE: {d.get('name')} ({d.get('model')})")
        print(f"Clients: {len(cl)} "
              f"({sum(1 for x in cl if x.get('type') == 'WIRED')} wired, "
              f"{sum(1 for x in cl if x.get('type') == 'WIRELESS')} wireless)")
        print(f"Gateway {gw.get('name')}: CPU {stats.get('cpuUtilizationPct')}%, "
              f"RAM {stats.get('memoryUtilizationPct')}%, uptime {stats.get('uptimeSec', 0) // 86400}d")
    else:
        sys.exit(f"Unknown command: {a.cmd}\n\n{__doc__}")


if __name__ == "__main__":
    main()
