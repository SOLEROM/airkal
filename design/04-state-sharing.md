---
noteId: "e1778390813211f198c7072a98948821"
tags: []

---

# State sharing & rate control

The share rate is **the knob the whole demo is about** — settable per-drone
or fleet-wide from the C2 layer at any moment.

## The broadcaster

Each agent runs a `StateBroadcaster` (`agent/broadcaster.py`) that publishes
the drone's own fused state on the `state` channel:

- **Deadline-based loop**: the next send deadline advances by `1/rate` from
  the previous deadline (not from "now"), so the observed rate tracks the
  requested rate even while it changes mid-flight.
- **Rate policy** (`common/config.py: clamp_rate`): a request of `0` (or
  anything ≤ 0) **pauses** sharing; any positive request is clamped into
  **[0.1, 10] Hz**. Agents boot at `DEFAULT_RATE_HZ` (5 Hz). A paused
  broadcaster keeps polling so an un-pause takes effect within ~0.2 s.
- The agent tracks both `rate_cmd` (what was requested) and `rate_applied`
  (what actually runs after clamping) — the fleet table shows
  `cmd → applied` so clamping is visible.

Only the share rate over the air changes — each drone's own PX4 navigation
is untouched. The drone always knows where *it* is; the question is how well
its **peers** know.

## The command path

```
web page slider / curl
  → POST /api/rate {"target": "all" | id, "hz": 0.5}     (validated, rate-limited)
  → C2 CmdFanout: one validated cmd message on the cmd channel (UDP 48010)
  → every agent hears it; applies it if target is "all" or its own id
  → StateBroadcaster.set_rate(hz)
```

The same path carries the pattern commands (`start`/`stop`/`land`) to the
flight driver. C2 keeps no rate state of its own — the applied rate is
whatever the agents report back in telemetry.

## What is actually sent

One `state` datagram is ~150 bytes of single-line JSON:

```json
{"ch":"state","id":2,"seq":417,"t":1752651123.481,
 "p":[3.1,-39.9,-35.0],"v":[4.2,0.3,0.0],
 "P":[0.11,0.11,0.05,0.02,0.02,0.01]}
```

The sender includes its EKF covariance diagonal `P`, so receivers can weight
each measurement by how good the *sender* thinks it is (see
[Kalman prediction](05-kalman-prediction.md)).

`p`/`v` are PX4 EKF2 **fused** estimates — `p` is not raw GPS and `v` is not
the offboard velocity command (offboard here is position + yaw only). For the
exact MAVLink provenance of each field see
[State signal provenance](04a-state-signals.md).

At 10 Hz × N drones this is a few kB/s on the wire; at 0.1 Hz it is nearly
nothing — the bandwidth chart on the front page shows exactly this.

## Per-drone override

`POST /api/rate` with a numeric `target` throttles a single drone. The demo
scenario: leave the fleet at its 5 Hz default and throttle one drone to
1 Hz (or 0.2 Hz for full drama) — on the map that drone's uncertainty
circles (as seen by any observer) balloon between its rarer updates and
snap tight on every arrival, while the others stay tight.
