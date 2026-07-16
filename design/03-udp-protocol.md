---
noteId: "d5d61100813211f198c7072a98948821"
tags: []

---

# UDP bus & wire protocol

## Transport

One destination address, **one port per channel**, any number of subscribers
per port on the same host (`common/udpbus.py`):

- Default mode is IPv4 subnet **broadcast on the loopback network**
  (`127.255.255.255`). The whole demo runs on one host; loopback broadcast
  needs no NIC, no IGMP, no routes, and survives network changes.
- **Multicast** (`239.42.0.1`) exists for multi-host setups:
  `AIRKAL_BUS_MODE=multicast`.
- All receive sockets set `SO_REUSEADDR` + `SO_REUSEPORT`, so the kernel
  delivers each datagram to *every* socket bound to the port — agents, C2
  and netstats all listen to the same channel concurrently.

## Channels

| Port | Channel | Who → whom | Rate |
|---|---|---|---|
| 48000 | `state` | agent → all agents | 0.1–10 Hz, runtime-controlled (the knob) |
| 48010 | `cmd` | C2 → agents | on demand |
| 48020 | `telemetry` | agent → C2 | 5 Hz fixed |
| 48030 | `stats` | netstats → C2 | 1 Hz fixed |

## Envelope

Every message on every channel is one single-line compact JSON object with a
common envelope:

```json
{"ch": "state", "id": 2, "seq": 417, "t": 1752651123.481, ...payload...}
```

- `ch` — channel name (must match the port it arrives on to be processed)
- `id` — sender id (drone id, or 0 for C2/netstats)
- `seq` — per-sender monotonically increasing counter (loss/ordering detection)
- `t` — sender wall-clock timestamp [s]

## Per-channel payloads

**state** — the payload under study, ~150 bytes:

```json
{"p": [x, y, z], "v": [vx, vy, vz], "P": [p11, p22, p33, v11, v22, v33]}
```

`p`/`v` are NED position [m] / velocity [m/s]; `P` is the 6-element
covariance **diagonal** (position + velocity variances) reported by the
sender's own EKF — the receiver uses it as measurement noise `R`. All three
are EKF2 fused estimates (`p` is not raw GPS, `v` is the measured velocity not
an offboard command); see [State signal provenance](04a-state-signals.md).

**cmd**:

```json
{"target": "all" | id, "cmd": "set_rate" | "pattern_start" | "pattern_stop" | "land", "hz": 0.5}
```

**telemetry** — the agent's full self-view: own `p/v/P`, `armed`, `mode`,
flight `phase`, `rate_cmd` / `rate_applied`, `peers` (its *predicted*
estimate of every peer: `p_hat`, `sigma`, `age`) and `counters`
(tx/rx totals, accepted/rejected packets, commands applied).

**stats** — per channel × sender: msgs/s and bytes/s over a 1 s window, a
10 s EMA, mean message size, cumulative totals and a loss estimate from
`seq` gaps.

## Validation everywhere

`common/msg.py` is the single wire-schema authority. Validation runs:

- at every **send** (`encode`) — fail fast on programming errors;
- at every **receive** boundary (`decode`) — malformed or schema-violating
  datagrams are **counted and dropped**, never crash a tool. Every receiver
  keeps a `malformed` counter you can inspect in telemetry/stats.

Checks include: known channel, finite numbers only (`NaN`/`Inf` rejected),
correct vector lengths, non-negative variances, plausible rate bounds, and
type strictness (booleans are not accepted where numbers are expected).
