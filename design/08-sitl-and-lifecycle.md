---
noteId: "183556a0813311f198c7072a98948821"
tags: []

---

# SITL, docker & lifecycle

## The PX4 containers

Each drone is one docker container (`sitl/`) running **headless PX4 SITL
with the SIH quadcopter model** (simulation-in-hardware: the vehicle
dynamics run *inside* PX4, so no external simulator process is needed and
the container stays small and deterministic).

- **Pinned PX4 version** in `sitl/VERSION`; `make build` builds the image
  once (~10–30 min). The entrypoint auto-detects the SIH airframe id from
  the build, so a version bump cannot silently break it.
- **Host networking**; PX4 instance *i* talks MAVLink to agent *i+1* on
  `udp:14540+i` (ports `18570+i` are also used by PX4). Lockstep keeps the
  simulation deterministic.
- Containers are labeled **`airkal-demo`** and named **`airkal-sitl-<i>`** —
  the same label the header badge and `make status` filter on.
- `sitl/params.override` is a PX4 parameter overlay applied *by the agents*
  over MAVLink at connect time (runtime-settable parameters only, no image
  rebuild needed).

## The agent's MAVLink side (`agent/mav.py`)

A background thread connects to the drone's PX4, requests the EKF2 output
streams and keeps the latest fused own-state:

- primary source: **ODOMETRY (msg 331) at 50 Hz** — pose + velocity
  covariance diagonals;
- position/velocity from **LOCAL_POSITION_NED** (plain NED, no frame
  gymnastics);
- fallback: if ODOMETRY covariance is absent or invalid, a conservative
  fixed covariance diagonal is used so the demo keeps working.

State older than 2 s is treated as stale (the broadcaster skips instead of
sending garbage).

## Lifecycle

`make help` lists every target. The important ones:

| Target | Effect |
|---|---|
| `make install` | python venv + dependencies |
| `make build` | build the pinned PX4 SITL image (one-time) |
| `make up N=3` | start N SITL containers, wait for MAVLink heartbeats |
| `make agents N=3` | start N agent processes (pidfiles in `var/run/`) |
| `make c2` | start the C2 server on :8080 (`C2_PORT=…` to change) |
| `make run N=3` | up + agents + c2 + netstats in one shot |
| `make stats` | live UDP traffic table in the terminal (netstats CLI) |
| `make status` | what is running right now |
| `make down` | stop everything, leave nothing behind |

Start order matters: agents wait for a PX4 heartbeat, so `make up` comes
before `make agents` (`make run` sequences it for you). Host processes are
managed via pidfiles in `var/run/`.

## netstats

`netstats/` joins **all four channels**, counts every datagram (including
its own 1 Hz stats messages — control-plane traffic too), renders a live
CLI table and publishes the aggregate on the stats channel for C2/web.
Per channel × sender it tracks msgs/s and bytes/s (1 s window + 10 s EMA),
mean message size, totals, and a loss estimate from envelope `seq` gaps.

## Verification

```bash
make test           # unit test suite
make verify N=3     # per instance: heartbeat + ODOMETRY @50 Hz with covariance
make smoke          # end-to-end on 1 drone: default rate ±10%, set_rate applied
make coverage       # unit tests + ≥80% gate on kalmanlib/ + common/
```

## Troubleshooting quick hits

- `make up` says no heartbeat → `docker logs airkal-sitl-1`; first boot
  takes a few seconds; ports `14540+i` / `18570+i` must be free.
- Agents log "waiting for PX4 heartbeat" → start order (`make up` first).
- No web updates → is C2 running (`make status`)? Charts also need netstats.
- Multi-host → `AIRKAL_BUS_MODE=multicast` switches the bus to `239.42.0.1`.
