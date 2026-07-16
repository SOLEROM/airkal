---
noteId: "fbae2d40813211f198c7072a98948821"
tags: []

---

# C2 server & API

`c2/main.py` — command & control. **Observer only** on the data side:
killing C2 never affects flight or peer tracking. It listens on the
telemetry and stats channels, keeps last-known fleet state in memory,
computes pairwise prediction errors, fans out commands, serves the web page
and pushes snapshots over WebSocket.

## FleetStore

- Ingests `telemetry` (48020) and `stats` (48030) datagrams; malformed
  packets are counted and dropped.
- `fleet()` returns each drone's latest telemetry with an `age` field;
  entries older than **10 s** are hidden as stale.
- Pushes a full JSON snapshot (`{t, fleet, stats, errors, docker}`) to every
  connected WebSocket client at **5 Hz**.

## Prediction-error tracking (`c2/errors.py`)

The demo's proof. For every observer/peer pair *(k, i)*:

```
error = | drone k's telemetry-reported prediction of peer i
         − drone i's own telemetry-reported position |
```

aligned **nearest-in-time** on drone i's recent state history (30 s kept,
pairing tolerance 1 s). Per pair, C2 tracks the current error and a rolling
max. Note that C2 computes no filter of its own — it only compares what the
agents themselves report, so the chart is an end-to-end measurement.

## Command fan-out (`c2/fanout.py`)

Every accepted API request becomes one validated `cmd` message on the cmd
channel (48010). C2 keeps no rate or flight state — the source of truth is
whatever the agents report back.

## Docker watch (`c2/dockerwatch.py`)

Polls `docker ps` every 3 s for containers labeled `airkal-demo` (the label
the lifecycle scripts apply) and includes the result in the snapshot — this
feeds the `sitl` badge in the page header. Degrades gracefully: if docker is
missing or the daemon is down, the badge shows "not available" rather than
an error.

## HTTP API (`c2/api.py`)

Consistent response envelope on every endpoint:
`{"ok": bool, "data": …, "error": …}`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/rate` | `{"target": "all" \| id, "hz": 0..100}` → set share rate |
| POST | `/api/pattern` | `{"target", "action": "start" \| "stop" \| "land"}` |
| GET | `/api/fleet` | latest per-drone telemetry |
| GET | `/api/stats` | latest netstats snapshot + prediction errors |
| GET | `/api/design` | list of these design pages |
| GET | `/api/design/{file}` | one design page as markdown |
| GET | `/ws` | WebSocket; server pushes snapshots at 5 Hz |
| GET | `/` + static | the web page (`web/`) |

Hardening (LAN demo, not an internet service, but still):

- all inputs validated (types, ranges, enum values);
- POST endpoints require `Content-Type: application/json`, which forces a
  CORS preflight and defeats cross-site `text/plain` form POSTs (CSRF);
- a token-bucket **rate limit per client address** guards the POSTs;
- design page names are pattern-checked and resolved strictly inside the
  `design/` folder (no path traversal);
- unhandled exceptions become a generic 500 envelope — no stack traces leak.

## Scripted control

```bash
curl -X POST http://localhost:8080/api/rate    -H 'Content-Type: application/json' -d '{"target":"all","hz":0.5}'
curl -X POST http://localhost:8080/api/pattern -H 'Content-Type: application/json' -d '{"target":"all","action":"start"}'
curl http://localhost:8080/api/fleet
```
