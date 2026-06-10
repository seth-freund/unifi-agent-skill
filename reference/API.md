# UniFi Integration API Reference

Verified against Network 10.4.x and Protect 7.1.x on UniFi OS (June 2026).
Endpoint availability varies slightly by version; the setup script probes
what your console actually supports.

Base host: your console, e.g. `https://192.168.1.1` (self-signed cert — TLS
verification off by default). Auth header on every request: `X-API-KEY: <key>`.
Keys are created in the UniFi console: Settings → Control Plane → Integrations.

## Network API — base `/proxy/network/integration/v1`

List endpoints paginate: `?offset=N&limit=N` → `{offset, limit, count, totalCount, data: []}`.
`{s}` = site id from `GET /sites` (most home consoles have exactly one).

| Method | Path | Notes |
|---|---|---|
| GET | `/info` | `{applicationVersion}` |
| GET | `/sites` | site list |
| GET | `/sites/{s}/devices` | UniFi gear (APs, switches, gateway, PDU) |
| GET | `/sites/{s}/devices/{id}` | detail incl. port/radio interfaces |
| GET | `/sites/{s}/devices/{id}/statistics/latest` | uptime, CPU/RAM %, load, uplink bps |
| POST | `/sites/{s}/devices/{id}/actions` | body `{"action":"RESTART"}` |
| POST | `/sites/{s}/devices/{id}/interfaces/ports/{idx}/actions` | `{"action":"POWER_CYCLE"}` (PoE) |
| GET | `/sites/{s}/clients` | connected clients (WIRED/WIRELESS, ip, mac, connectedAt, uplinkDeviceId) |
| GET | `/sites/{s}/clients/{id}` | single client |
| POST | `/sites/{s}/clients/{id}/actions` | guest authorization actions |
| GET | `/sites/{s}/networks` | networks/VLANs |
| GET | `/sites/{s}/wifi/broadcasts` | SSIDs with security + bands |
| GET | `/sites/{s}/wans` | WAN config/status |
| GET | `/sites/{s}/acl-rules` | ACL rules |
| GET/POST | `/sites/{s}/hotspot/vouchers` | guest vouchers; POST `{"name","timeLimitMinutes","count"}` |

Not available as of Network 10.4 (404): `/wlans`, `/firewall-policies`,
`/port-forwarding`, `/traffic-routes`, `/dns`. Client block/unblock is not
exposed by the Integration API — use ACL rules or the UI.

## Protect API — base `/proxy/protect/integration/v1`

Responses are plain JSON arrays/objects (not paginated envelopes).

| Method | Path | Notes |
|---|---|---|
| GET | `/meta/info` | `{applicationVersion}` |
| GET | `/cameras`, `/cameras/{id}` | state, `featureFlags.smartDetectTypes`, settings |
| PATCH | `/cameras/{id}` | update camera settings |
| GET | `/cameras/{id}/snapshot?highQuality=true` | current JPEG |
| GET | `/sensors`, `/lights`, `/chimes`, `/liveviews`, `/viewers`, `/nvrs` | other Protect devices |
| GET | `/files/motion` | motion files listing |
| WS | `wss://…/subscribe/events` | live event stream (smart detections); header X-API-KEY |
| WS | `wss://…/subscribe/devices` | live device state updates |

Smart-detect types vary by camera model and license: `person`, `vehicle`,
`animal`, `package` (doorbells), `face` and `licensePlate` (AI-series).
Check each camera's `featureFlags.smartDetectTypes` — the inventory lists them.

No REST `/events` history endpoint as of Protect 7.1 — historical event queries
require capturing the websocket stream to a log.
