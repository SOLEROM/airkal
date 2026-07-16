# Low-rate peer state sharing over UDP with Kalman prediction (minimal SITL demo)ד

**Goal.** Build a small, self-contained demo that proves one concept:

> Drones in a simulated fleet can share their GPS/position state with each other
> at a **low, runtime-controllable rate** over UDP, and every receiver can bridge
> the silent gaps with a small **Kalman filter per peer** that predicts where each
> peer is between updates — with honest, growing uncertainty.

The demo runs on **PX4 SITL** (spun up by hand, on demand), uses PX4's own EKF2
as the source of each drone's fused state ("the Kalman from PX4"), passes all
inter-tool data over **plain UDP**, and is operated and observed from a **web
front page**. The design is intentionally minimal — just enough to demonstrate
the concept — while the SITL environment itself is built to be robust and easy
to modify.

---

## 1. Concept in one page

- Each drone's PX4 EKF2 already fuses GPS+IMU+baro+mag internally at high rate.
  Nobody needs to re-estimate a peer from raw sensors — the peer already did the
  hard filtering. So the thing to transmit is the sender's **fused state +
  timestamp + covariance**, extracted from PX4 over MAVLink.
- Each receiver keeps a tiny Kalman filter **per peer** (constant-velocity
  model). On packet arrival it updates from the received state; between packets
  it runs only the **prediction step**, so a continuous estimate of every peer —
  position, velocity, and a covariance that grows with silence — is always
  available regardless of the share rate.
- Why it works — worst-case mid-gap position error for a peer flying ≤ 6 m/s,
  accelerating ≤ 1.5 m/s², share period T:

  | Share rate | Position-only hold ≈ v·T | CV prediction (share p, v, t) ≤ ½·a·T² |
  |---|---|---|
  | 10 Hz | 0.6 m | 0.008 m |
  | 2 Hz | 3 m | 0.19 m |
  | **1 Hz** | 6 m | **0.75 m** |
  | 0.5 Hz | 12 m | 3 m |

  A 1 Hz share that includes velocity and a timestamp predicts better than a
  10 Hz position-only share. The Kalman filter formalizes this and adds the
  honesty term: P grows between packets, so consumers can react to uncertainty
  instead of a binary "stale" flag.
- The demo makes this visible: turn the share rate down from a web page and
  watch bandwidth collapse while prediction error stays small and the
  uncertainty circles breathe between updates.

**Scope discipline.** Only the share rate over the air changes. Each drone's own
navigation (PX4's internal GPS/EKF2 rates) stays untouched and full-quality.

---

## 2. System overview

```
                        ┌────────────────────────────────────────────┐
                        │  Web front page (browser)                  │
                        │  map · rate slider · bandwidth · errors    │
                        └───────────────▲────────────────────────────┘
                                        │ HTTP + WebSocket :8080
                        ┌───────────────┴────────────────┐
                        │  C2 — command & control server │
                        └───▲──────────────▲─────────┬───┘
              telemetry :48020   stats :48030    commands :48010
                    (UDP)            (UDP)           (UDP)
   ┌────────────────┼────────────────┼────────────────┼──────────────┐
   │                │                │                ▼              │
   │  ┌─────────┐   │           ┌────┴─────┐   ┌────────────┐        │
   │  │ agent 1 │───┘           │ netstats │   │ agents 1..N│        │
   │  └────▲────┘               │ (sniffer)│   └────────────┘        │
   │       │ MAVLink            └────▲─────┘                         │
   │  ┌────┴─────┐                   │ listens on ALL UDP channels   │
   │  │ PX4 SITL │     state broadcast :48000 (UDP, agent ↔ agent)   │
   │  │ inst. 1  │  ◄── every agent both sends and receives here ──► │
   │  └──────────┘                                                   │
   │        … one PX4 SITL instance + one agent per drone, 1..N …    │
   └─────────────────────────────────────────────────────────────────┘
```

- **All inter-tool traffic is UDP** on a single multicast group (fallback:
  subnet broadcast), one port per channel. Every tool subscribes to the
  channels it needs; `netstats` subscribes to all of them and therefore sees
  every byte the system exchanges, passively.
- **No central data broker.** Agents talk peer-to-peer on the state channel.
  C2 is a thin command/observation layer, not a dependency of the data path —
  killing C2 must not affect flight or peer tracking.
- **Everything is spun up by hand, on demand**: one script starts N SITL
  instances + N agents; C2, netstats, and the web page are started the same
  way. No always-on services, no orchestrator.

---

## 3. Minimum components (the complete list)

Six components. Nothing else is built.

| # | Component | One-liner | Runs as |
|---|---|---|---|
| 1 | `sitl/` | PX4 SITL environment: pinned image, headless, N instances on demand | docker container per drone |
| 2 | `kalmanlib/` | CV Kalman filter + per-peer tracker bank (pure numpy, unit-tested) | library |
| 3 | `agent/` | Per-drone process: MAVLink→state extraction, flight driver, UDP state broadcaster (controllable rate), peer trackers, command handler, telemetry reporter | host process ×N |
| 4 | `c2/` | Command & control server: REST/WebSocket API, command fan-out over UDP, telemetry/stats aggregation, serves the web page | host process ×1 |
| 5 | `netstats/` | UDP traffic statistics: passive listener on all channels, per-channel/per-sender byte & message rates, CLI view + reports to C2 | host process ×1 |
| 6 | `web/` | Single front page: fleet table, 2D map with uncertainty circles, rate controls, live bandwidth & prediction-error charts | static files served by C2 |

Plus one shared module `common/` (message schema, UDP socket helpers, config
constants) used by 3–5 — glue, not a component.

---

## 4. UDP channels and message schema

One multicast group `239.42.0.1` (host-local demo; fallback: broadcast on a
docker bridge subnet — decided once in Phase 1 and hidden behind
`common/udpbus.py`). One port per channel:

| Port | Channel | Direction | Content | Nominal rate |
|---|---|---|---|---|
| 48000 | `state` | agent → all agents | shared drone state (the payload under study) | 0.1–10 Hz, runtime-controlled |
| 48010 | `cmd` | C2 → agents | control commands (set rate, start/stop pattern) | sporadic |
| 48020 | `telemetry` | agent → C2 | own EKF state + peer estimates + counters (for display/eval only) | 5 Hz fixed |
| 48030 | `stats` | netstats → C2 | aggregated traffic statistics | 1 Hz |

Every message on every channel is single-line JSON with a common envelope —
this is what makes the statistics tool trivial and the system debuggable with
`tcpdump`/`socat`:

```json
{"ch":"state","id":3,"seq":417,"t":1789475123.412, ...payload}
```

**`state` payload** (~180 B typical):

```json
{"ch":"state","id":3,"seq":417,"t":1789475123.412,
 "p":[12.31,-40.22,-30.05],
 "v":[3.10,0.42,0.00],
 "P":[0.25,0.25,0.4,0.04,0.04,0.09]}
```

| Field | Content | Why |
|---|---|---|
| `t` | sender time of validity (host clock; all sim processes share it) | predict from event time, not arrival time |
| `seq` | monotonic counter | loss measurement, out-of-order drop |
| `p`, `v` | EKF2 NED position + velocity (shared home origin) | CV prediction — the core of the concept |
| `P` | covariance diagonal (pos+vel) from PX4's EKF | receiver's measurement noise R; honest initialization |

**`cmd` payload**: `{"ch":"cmd","target":"all"|id,"cmd":"set_rate","hz":1.0}`
(also `"pattern_start"`, `"pattern_stop"`, `"land"`). Agents acknowledge by
reflecting the applied value in their next telemetry message.

**`telemetry` payload**: own state (same fields as `state`) + per-peer
`{id: {"p_hat":[..],"sigma":s,"age":a}}` + counters
`{"tx_msgs":..,"tx_bytes":..,"rx_msgs":..,"rate_hz":..}`.

---

## 5. Component specifications

### 5.1 `sitl/` — the PX4 SITL environment (built robust)

This is the one part engineered for change, because everything else leans on it.

- **Pinned PX4 release** (e.g. v1.15.x tag) built into a docker image once;
  the image is versioned in the repo (`sitl/Dockerfile`, `sitl/VERSION`).
- **Headless** SITL with lockstep, no GUI (Gazebo headless or none); one
  container per drone, instance number `i` gives `MAV_SYS_ID=i` and the
  standard per-instance MAVLink port offsets (agent connects to
  `udp:14540+i`).
- **Parameter overlay file** (`sitl/params.override`) applied at start — EKF2
  enabled, home position shared across instances so NED frames coincide. Any
  future PX4 tuning is one file, no image rebuild.
- **Spin-up by hand, on demand** — the only lifecycle interface:

  ```
  ./sim.sh up N      # start N SITL containers (+ health wait)
  ./sim.sh agents N  # start N agents (or: sim.sh up N --with-agents)
  ./sim.sh c2        # start C2 (serves web page on :8080)
  ./sim.sh stats     # start netstats (CLI view)
  ./sim.sh down      # stop everything, clean up
  ./sim.sh status    # what is running, which ports
  ```

- **Getting the Kalman filter from PX4** — documented and verified in Phase 1:
  - Primary: request `ODOMETRY` (msg 331) at 50 Hz via `SET_MESSAGE_INTERVAL`
    — pose + velocity **+ covariance matrices** in one message; this feeds
    `p`, `v`, `P` of the `state` message directly.
  - Fallback: `LOCAL_POSITION_NED` (+ `ESTIMATOR_STATUS` variances) if a PX4
    build doesn't populate ODOMETRY covariance.
  - Offline: PX4 ulogs (`estimator_states`) remain accessible in the container
    for spot-checking the covariances we transmit.

### 5.2 `kalmanlib/` — the estimator (small, tested, generic)

- `kf.py` — linear Kalman filter (predict/update), numpy-only.
- `models.py` — constant-velocity F(dt), Q(dt) with white-noise-accel
  σ_a ≈ 1.5–3 m/s². **CV only** — no CA/CT/IMM, no event-triggered policies;
  those are future work, not this demo.
- `peer_tracker.py` — `PeerTrackerBank`: `on_packet(msg)` (init/update, drop
  out-of-order by `seq`/`t`), `predict_all(t_query) → {id: (p̂, v̂, P)}`.
- TDD, ≥80% coverage: golden tests vs analytic 1-D solution, NEES-consistency
  test on a simulated CV track, out-of-order/duplicate packet tests.

### 5.3 `agent/` — one per drone

Single Python process, ~5 small modules:

- **mavlink adapter** — connects `udp:14540+i`, sets message intervals, keeps
  latest own EKF state (p, v, P, t).
- **flight driver** — makes the demo move: arm, takeoff to 30 m + 5·i m
  separation, then a slow orbit (radius 40 m, period 60 s, per-drone phase
  offset) via offboard setpoints. Deterministic motion with real turns — good
  prediction material. `pattern_start/stop/land` from the cmd channel.
- **state broadcaster** — publishes the `state` message on :48000 at
  `rate_hz`, a runtime variable (0 = paused, clamp 0.1–10 Hz).
  **This variable is the knob the whole demo is about**, settable per-drone or
  fleet-wide from the C2 layer at any moment.
- **peer tracking** — feeds received `state` messages into `PeerTrackerBank`;
  queries predictions at 10 Hz for telemetry.
- **telemetry + command handler** — 5 Hz telemetry to :48020 (own state, peer
  estimates, counters, current applied rate); applies `cmd` messages.

### 5.4 `c2/` — command & control server

- Listens on `telemetry` and `stats` channels; keeps last-known fleet state
  in memory (no database).
- REST API: `POST /api/rate {"target":"all"|id,"hz":1.0}`,
  `POST /api/pattern {"action":"start"|"stop"|"land"}`, `GET /api/fleet`,
  `GET /api/stats`. Each POST fans out a `cmd` UDP message.
- WebSocket `/ws`: pushes fleet snapshots + stats + computed prediction errors
  to the browser at ~5 Hz.
- **Prediction-error computation** (the demo's proof): for every pair (k, i),
  error = |drone k's telemetry-reported estimate of peer i − drone i's own
  telemetry-reported state|, nearest-in-time alignment. Per-pair current value
  + rolling max.
- Serves `web/` as static files on :8080. Stateless; killing/restarting it
  never affects agents.

### 5.5 `netstats/` — UDP traffic statistics (the new tool)

Answers "how much data are we actually passing over UDP between the tools?"

- Passively joins **all four channels** (48000/48010/48020/48030) and, for
  every packet, records: channel, sender id (from the envelope), payload
  bytes, arrival time. No participation in the data path.
- Aggregates per channel × sender and per channel total: msgs/s, bytes/s
  (1 s window + 10 s EMA), mean msg size, cumulative totals, and for the
  `state` channel: observed inter-arrival vs commanded rate, and loss estimate
  from `seq` gaps.
- Two outputs:
  - **CLI view** — live-refreshing table in the terminal (`./sim.sh stats`).
  - **`stats` messages at 1 Hz** on :48030 → C2 → bandwidth panel on the web
    page.
- Sanity cross-check: agents' own `tx_msgs/tx_bytes` counters (in telemetry)
  should match netstats' passive counts; the web page shows both.

### 5.6 `web/` — the front page

One static page (vanilla JS + WebSocket + canvas; no build toolchain), four
panels:

1. **Fleet table** — per drone: id, armed/mode, position, commanded vs applied
   share rate, tx msgs/s, last-seen age.
2. **Map** — top-down 2D NED view: true positions (from telemetry) and, for a
   selected observer drone, its *predicted* peers with **σ uncertainty
   circles** that visibly grow between updates at low rates.
3. **Controls** — global rate slider (0.1–10 Hz, log scale) + per-drone
   override; pattern start/stop/land buttons. Slider → `POST /api/rate`.
4. **Charts** — bytes/s per channel over time (stacked, from netstats) and
   per-pair prediction error over time. The demo's money shot: rate slider
   goes down → state-channel bytes/s drops ~linearly → error rises only
   slightly, uncertainty grows honestly.

---

## 6. Runtime rate control — end-to-end path

```
web slider (1 Hz) → POST /api/rate → C2 → {"ch":"cmd","cmd":"set_rate","hz":1.0} on :48010
  → each agent updates its broadcaster period immediately
  → applied rate reflected in next telemetry → fleet table shows commanded=applied
  → netstats shows state-channel bytes/s dropping within ~2 s
```

Also scriptable without the browser: `curl -X POST :8080/api/rate -d '{"target":"all","hz":0.5}'`.

---

## 7. Repository layout

```
airkal/
  sim.sh                  # the single by-hand entry point (up/agents/c2/stats/down/status)
  sitl/                   # Dockerfile, params.override, VERSION, health-wait script
  common/                 # msg.py (schema+validation), udpbus.py, config.py (ports, group)
  kalmanlib/              # kf.py, models.py, peer_tracker.py
  agent/                  # main.py, mav.py, flight.py, broadcaster.py, tracker_io.py
  c2/                     # main.py, api.py, fanout.py, errors.py
  netstats/               # main.py, aggregate.py, cliview.py
  web/                    # index.html, app.js, map.js, charts.js, style.css
  tests/                  # unit: kalmanlib, common; integration: 1-instance smoke test
  plan2.md
```

Conventions: Python ≥3.10; files small and focused; schema validation at every
UDP receive boundary (malformed packets counted and dropped, never crash);
seeded/deterministic where applicable.

---

## 8. Build order (phases, each independently verifiable)

**P1 — SITL environment (≈1 day).**
Docker image (pinned PX4), `sim.sh up/down/status`, param overlay, shared home.
Verification script prints, for each of 3 instances: heartbeat, EKF `ODOMETRY`
at 50 Hz **with covariance values**. Decide multicast-vs-broadcast here and
freeze it in `common/udpbus.py`.
*Acceptance: `./sim.sh up 3` → 3 healthy instances; EKF state + covariance
streaming from all; `./sim.sh down` leaves nothing behind.*

**P2 — kalmanlib + agent (≈2 days).**
TDD the library first; then the agent: fly the orbit pattern, broadcast
`state` at a default 2 Hz, track peers, log predicted-vs-received residuals.
*Acceptance: 3-drone run where each agent tracks both peers; at 1 Hz share the
logged peer prediction error stays < 1.5 m during orbit; library tests ≥80%
coverage.*

**P3 — C2 + netstats (≈1 day).**
Command fan-out, telemetry aggregation, REST API, netstats CLI + stats channel.
*Acceptance: `curl` rate change 2 Hz → 0.5 Hz visibly drops state-channel
bytes/s in the netstats table within 2 s, and every agent's applied rate
updates; agent self-counters match netstats passive counts within 2%.*

**P4 — web front page (≈1–1.5 days).**
Map with uncertainty circles, slider, charts, fleet table; wire WebSocket.
*Acceptance: the full demo runbook (§9) works start-to-finish from the browser.*

Total: ~5 working days.

---

## 9. Demo runbook (the by-hand flow, start to finish)

```bash
./sim.sh up 3           # PX4 SITL ×3
./sim.sh agents 3       # agents connect, idle on ground
./sim.sh c2             # C2 up, http://localhost:8080
./sim.sh stats          # optional terminal stats view
# in the browser:
#  1. Pattern → Start: drones take off, begin orbits; map shows motion
#  2. Rate slider at 10 Hz: note state-channel bytes/s and near-zero error
#  3. Slide to 1 Hz: bytes/s drops ~10×; uncertainty circles pulse between
#     updates; prediction error stays sub-meter
#  4. Slide to 0.2 Hz: circles grow large; error grows during turns — the
#     honest-uncertainty story
#  5. Per-drone override: set drone 2 alone to 0.2 Hz, compare pairs
#  6. Pattern → Land, then:
./sim.sh down
```

---

## 10. Testing

- **Unit (TDD, ≥80% on `kalmanlib/` + `common/`)**: KF golden tests, CV F/Q
  properties, NEES consistency, tracker out-of-order/duplicate/loss handling,
  schema round-trip + malformed-input rejection, rate-clamp logic.
- **Integration smoke test** (CI-runnable, 1 SITL instance): `sim.sh up 1`,
  assert EKF stream present, agent broadcasts at commanded rate ±10%,
  `set_rate` cmd applied, teardown clean.
- **Demo acceptance** = §8 P4 criteria via the §9 runbook.

---

## 11. Risks & chosen defaults

| Risk / decision | Position |
|---|---|
| Multicast vs broadcast quirks (docker/host) | Decided empirically in P1; isolated in `common/udpbus.py` so nothing else cares |
| PX4 ODOMETRY covariance not populated in chosen build | Fallback path specified (LOCAL_POSITION_NED + ESTIMATOR_STATUS); P1 verifies before anything depends on it |
| Lockstep time vs wall clock under load | All processes share the host clock; telemetry carries both `t` and MAVLink `time_boot_ms` so skew is detectable |
| C2 as accidental single point of failure | Forbidden by design: data path is peer-to-peer; C2/web/netstats are observers + command sources only |
| Turns break constant-velocity prediction | Expected and *shown* (error chart during orbit turns); σ_a default doubled to 3 m/s² for headroom |
| Scope creep | The six components in §3 are the whole build; anything else goes to §12 |

Defaults: NED about the shared home origin; single-line JSON over UDP (byte
size is itself a demo metric — measured, not optimized); CV model with
σ_a = 3 m/s²; default share rate 2 Hz; telemetry fixed at 5 Hz and displayed
separately in stats so it's never confused with the payload under study.

## 12. Explicitly out of scope (future work)

Event-triggered sending (send-on-deviation + heartbeat), richer motion models
(CA/CT/IMM), channel impairment simulation (loss/latency injection), synthetic
trajectory playground, log replay tooling, binary packing of the state
message, and consuming peer predictions in any control loop (e.g. separation
keeping). The message schema (`t`, `seq`, `P`) is designed so all of these
bolt on without breaking the wire format.
