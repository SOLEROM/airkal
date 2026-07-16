---
noteId: "b5f73120813211f198c7072a98948821"
tags: []

---

# Overview

airkal is a self-contained PX4 SITL demo of **one concept**: drones share
their fused GPS/position state with each other at a **low, runtime-controllable
rate** over UDP, and every receiver bridges the gaps with a small **Kalman
filter per peer**. Position, velocity and an honestly growing uncertainty are
always available, regardless of the share rate.

## The idea in one loop

1. Each drone extracts its own fused state (position, velocity, covariance)
   from PX4's EKF over MAVLink.
2. It broadcasts that state on a shared UDP channel at a chosen rate —
   anywhere from 10 Hz down to 0.1 Hz, or paused entirely.
3. Every *other* drone folds those packets into a per-peer Kalman filter
   (constant-velocity model) and can ask "where is peer *i* **right now**?"
   at any moment — between packets the filter predicts, and its covariance
   grows to say how much that prediction should be trusted.
4. A C2 web page lets you turn the rate knob live and *see* the trade-off:
   lower rate → less bandwidth → larger uncertainty circles and larger
   real prediction error.

The interesting part is that nothing breaks when the rate drops — the
estimate just gets honestly worse, and the system tells you by how much.

## What this is *not*

- Not a swarm framework: flight is a fixed, deterministic orbit pattern
  whose only job is to generate interesting motion (real turns make the
  constant-velocity model visibly imperfect).
- Not a network stack: transport is plain UDP broadcast on loopback,
  single-line JSON per datagram, chosen for observability over efficiency.
- Not internet-facing: the C2 API is a LAN demo tool with light hardening
  (input validation, rate limit, CSRF-resistant content-type check).

## Running it

```bash
make install        # python venv + dependencies
make build          # PX4 SITL docker image (one-time)
make run N=3        # SITL ×3 + agents ×3 + C2 + netstats
# open http://localhost:8080 → pattern "start" → play with the rate slider
make down           # stop everything
```

## Reading guide

| Page | What it covers |
|---|---|
| [Architecture](02-architecture.md) | Components, processes, data flow |
| [UDP bus & wire protocol](03-udp-protocol.md) | Channels, ports, message schema, validation |
| [State sharing & rate control](04-state-sharing.md) | The broadcaster and the rate knob |
| [State signal provenance](04a-state-signals.md) | What `p`/`v`/`P` really are (fused, not raw GPS / not the offboard command) |
| [Kalman prediction](05-kalman-prediction.md) | The per-peer filter and its uncertainty |
| [C2 server & API](06-c2-server.md) | FleetStore, error tracking, REST/WebSocket |
| [Web UI page-by-page](07-web-ui.md) | Every panel of the front page explained |
| [SITL, docker & lifecycle](08-sitl-and-lifecycle.md) | PX4 containers, scripts, verification |
