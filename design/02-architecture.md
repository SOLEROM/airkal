---
noteId: "c438a2f0813211f198c7072a98948821"
tags: []

---

# Architecture

Five components, four UDP channels, one rule: **the data path is
peer-to-peer**. C2, netstats and the web page are observers/command sources
only — killing any of them never affects flight or peer tracking.

## Components

| Component | Runs as | Role |
|---|---|---|
| `sitl/` | docker container ×N (host network) | PX4 SIH quadcopter, headless, lockstep |
| `agent/` | host process ×N | per-drone: EKF extraction, flight, share, track |
| `c2/` | host process ×1 | REST + WebSocket + web page; command fan-out |
| `netstats/` | host process ×1 | passive UDP traffic statistics |
| `web/` | your browser | live dashboard (this page) |

## Data flow

```
             MAVLink udp:14540+i
 PX4 SITL i <====================> agent i
                                     |  ^
             state @ rate ───────────┘  |   (agent ↔ agent, the payload
             48000, broadcast ──────────┘    under study)
                                     |
             telemetry @ 5 Hz ───────┼──────────► C2 ──► WebSocket @ 5 Hz ──► browser
             48020                   |            ▲
             cmd (set_rate, pattern) ◄────────────┘  REST POST /api/…
             48010
                                                  ▲
             stats @ 1 Hz  ───────── netstats ────┘   (listens on all channels)
             48030
```

- **state** (48000): every agent broadcasts its own fused state; every other
  agent's tracker bank consumes it. This is the only link the demo studies.
- **cmd** (48010): C2 fans out `set_rate` / `pattern_start` / `pattern_stop`
  / `land`, targeted at `"all"` or a single drone id.
- **telemetry** (48020): each agent reports its full self-view at 5 Hz —
  own state, flight phase, applied rate, its *predictions of every peer*,
  and counters. Display/evaluation only.
- **stats** (48030): netstats publishes per-channel × per-sender traffic
  aggregates once a second.

## Why the observer split matters

Drone k's belief about drone i exists **only inside agent k** — C2 does not
compute it. C2 merely compares what agent k *says* it predicts (telemetry)
with what agent i *says* its true position is (telemetry), which is how the
prediction-error chart is an honest end-to-end measurement rather than a
simulation of one.

## Process lifecycle

Everything is started and stopped by `make` targets wrapping `scripts/*.sh`:

- `make up N=3` — start N SITL containers (label `airkal-demo`,
  names `airkal-sitl-<i>`), wait for MAVLink heartbeats.
- `make agents N=3` — start N agent processes (pidfiles in `var/run/`).
- `make c2` / `make run` — C2 server; `make run` = up + agents + c2 +
  background netstats.
- `make down` — stop processes and containers, leave nothing behind.
- `make status` — one-line view of what is currently running.

See [SITL, docker & lifecycle](08-sitl-and-lifecycle.md) for details.

## Repository layout

```
common/       config.py, msg.py (wire schema), udpbus.py (UDP transport)
kalmanlib/    kf.py, models.py (CV), peer_tracker.py
agent/        main.py, mav.py, flight.py, broadcaster.py, tracker_io.py
c2/           main.py, api.py, fanout.py, errors.py, dockerwatch.py
netstats/     main.py, aggregate.py, cliview.py
web/          index.html, app.js, map.js, charts.js, design.js, style.css
design/       these documentation pages
sitl/         Dockerfile (pinned PX4), entrypoint, params.override
scripts/      lifecycle scripts, verify_sitl.py, smoke.sh
tests/        unit tests (kalmanlib, common, agent, c2, netstats)
```
