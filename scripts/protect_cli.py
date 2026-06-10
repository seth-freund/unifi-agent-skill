#!/usr/bin/env python3
"""UniFi Protect CLI.

Usage:
  protect_cli.py cameras [--json]
  protect_cli.py camera <id-or-name>
  protect_cli.py snapshot <id-or-name> [-o FILE] [--all DIR]
  protect_cli.py sensors | lights | chimes | liveviews | nvr | viewers
  protect_cli.py watch [--types person,vehicle,package,animal]   # live events (needs 'websockets' pkg)
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path
from unifi_client import UnifiClient


def jprint(obj):
    print(json.dumps(obj, indent=2, default=str))


def resolve(c, ident):
    """Accept a 24-hex camera ID or a (fuzzy) camera name, so users can say
    'doorbell' instead of pasting IDs."""
    if re.fullmatch(r"[0-9a-f]{24}", ident):
        return c.camera(ident)
    return c.camera_by_name(ident)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-o", "--out")
    ap.add_argument("--all", help="Directory: snapshot every camera into it")
    ap.add_argument("--types", default="")
    a = ap.parse_args()
    c = UnifiClient()

    if a.cmd == "cameras":
        cams = c.cameras()
        if a.json:
            jprint(cams)
        else:
            for x in cams:
                ff = x.get("featureFlags") or {}
                print(f"{x.get('name'):20s} {x.get('state'):12s} id={x.get('id')} "
                      f"smart={','.join(ff.get('smartDetectTypes', []))}")
    elif a.cmd == "camera":
        jprint(resolve(c, a.args[0]))
    elif a.cmd == "snapshot":
        if a.all:
            out = Path(a.all)
            out.mkdir(parents=True, exist_ok=True)
            for cam in c.cameras():
                try:
                    data = c.snapshot(cam["id"])
                    name = re.sub(r"\W+", "_", cam["name"]).strip("_").lower()
                    (out / f"{name}.jpg").write_bytes(data)
                    print(f"saved {out / (name + '.jpg')} ({len(data)} bytes)")
                except Exception as e:
                    print(f"FAILED {cam.get('name')}: {e}", file=sys.stderr)
        else:
            cam = resolve(c, a.args[0])
            data = c.snapshot(cam["id"])
            out = a.out or re.sub(r"\W+", "_", cam["name"]).strip("_").lower() + ".jpg"
            Path(out).write_bytes(data)
            print(f"saved {out} ({len(data)} bytes)")
    elif a.cmd in ("sensors", "lights", "chimes", "liveviews", "viewers"):
        jprint(getattr(c, a.cmd)())
    elif a.cmd == "nvr":
        jprint(c.nvrs())
    elif a.cmd == "watch":
        # Live smart-detection stream over the Protect websocket. This is the
        # only way to observe events — the Integration API has no REST event
        # history endpoint — so pipe this to a file for a queryable event log.
        try:
            import asyncio
            import ssl as _ssl
            import websockets
        except ImportError:
            sys.exit("Install dependency first: pip install websockets")
        want = {t.strip() for t in a.types.split(",") if t.strip()}
        cams = {x["id"]: x["name"] for x in c.cameras()}

        async def run():
            ctx = _ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
            async with websockets.connect(
                    c.events_ws_url(), ssl=ctx,
                    additional_headers={"X-API-KEY": c.cfg["api_key"]}) as ws:
                print("Connected. Watching for events... (Ctrl-C to stop)")
                async for msg in ws:
                    try:
                        ev = json.loads(msg)
                    except Exception:
                        continue
                    item = ev.get("item", ev)
                    etype = ev.get("type", "")
                    smart = item.get("smartDetectTypes") or []
                    if want and not (want & set(smart)):
                        continue
                    cam = cams.get(item.get("camera") or item.get("device"), "?")
                    ts = time.strftime("%H:%M:%S")
                    print(f"[{ts}] {cam}: {etype} {','.join(smart) or item.get('type', '')}")

        try:
            asyncio.run(run())
        except KeyboardInterrupt:
            pass
    else:
        sys.exit(f"Unknown command: {a.cmd}\n\n{__doc__}")


if __name__ == "__main__":
    main()
