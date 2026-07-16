---
noteId: "f5009f90813311f198c7072a98948821"
tags: []

---

# State signal provenance — what `p`, `v`, `P` really are

The shared `state` message carries three numeric fields — position `p`,
velocity `v`, covariance `P` — extracted from PX4 by the agent's MAVLink
adapter (`agent/mav.py`). This page pins down **exactly** what each one is,
because two of them are easy to misread:

- `p` is **not** raw GPS.
- `v` is **not** the offboard velocity you command in the flight driver.

Both are PX4 **EKF2 fused estimates** of the vehicle's *actual* state.

## At a glance

| Field | MAVLink source | What it is | What it is **not** |
|---|---|---|---|
| `p` | `LOCAL_POSITION_NED.x/y/z` | EKF2-fused NED position [m] about the shared home origin | not raw GPS lat/lon/alt (`GPS_RAW_INT`), not a setpoint |
| `v` | `LOCAL_POSITION_NED.vx/vy/vz` | EKF2-fused/estimated ground velocity [m/s] (the drone's *measured* motion) | not the offboard velocity command — offboard here injects **position + yaw only** |
| `P` | `ODOMETRY` pose/velocity covariance diagonals | EKF2's own uncertainty in `p`,`v` | not derived from `LOCAL_POSITION_NED` (a *different* message) |

## Position `p` — fused, not raw GPS

`p` comes from the `LOCAL_POSITION_NED` message (`agent/mav.py:148-158`,
`_on_local_position`): `[msg.x, msg.y, msg.z]`. That is EKF2's **fused**
position in the local NED frame relative to the shared home origin. GPS is one
of the sensors EKF2 fuses — together with IMU, barometer and magnetometer — so
GPS *feeds* this value, but the value is the filtered estimate in metres, not
the raw GNSS fix.

If we ever wanted the raw fix instead, that would be a different message
(`GPS_RAW_INT`), which the agent deliberately does not read. Sharing the fused
NED position is what keeps every drone in one common metric frame with no
per-packet coordinate conversion.

## Velocity `v` — measured motion, not the offboard command

`v` comes from the same `LOCAL_POSITION_NED` message
(`[msg.vx, msg.vy, msg.vz]`): EKF2's **estimated ground velocity**, i.e. how
fast the vehicle is *actually* moving as the filter sees it.

It is **not** the velocity we command in offboard mode, and in fact the flight
driver never injects a velocity at all. Offboard control here is
**position + yaw only**:

- `FlightDriver` (`agent/flight.py`) flies the orbit by streaming position
  setpoints (`send_position_setpoint`), never velocity setpoints.
- `send_position_setpoint` (`agent/mav.py:243-251`) sends
  `SET_POSITION_TARGET_LOCAL_NED` with type mask
  `_POS_YAW_TYPE_MASK = 0x09F8` (`agent/mav.py:36`), which tells PX4 to use
  position + yaw and **ignore** velocity and acceleration. The velocity fields
  in that message are passed as literal zeros and masked out.

So the commanded and the reported velocities are fully decoupled: PX4's
controller decides what velocity to fly to reach each position setpoint, and
`v` reports the resulting *observed* velocity from EKF2.

### Why measured, not commanded, is the right choice

The per-peer Kalman filter uses a constant-velocity model
(see [Kalman prediction](05-kalman-prediction.md)): between packets it
propagates each peer forward as `p' = p + v·dt`. For that to predict where a
peer *will be*, `v` must be the peer's true current velocity — not a setpoint
it may not have reached yet. Using the commanded velocity would inject error
exactly during transients and turns, defeating the whole point that a 1 Hz
share carrying velocity beats a 10 Hz position-only share.

## Covariance `P` — from a second message

`P` is the 6-element diagonal `[pos_x, pos_y, pos_z, vel_x, vel_y, vel_z]`
variance. It does **not** come from `LOCAL_POSITION_NED` (which carries no
uncertainty) — it is taken from the `ODOMETRY` message
(`agent/mav.py:160-170`, `_on_odometry`), which reports EKF2's pose and
velocity covariance matrices; the agent keeps their diagonal elements.

Two EKF2 outputs are therefore stitched together into one shared state:
`LOCAL_POSITION_NED` supplies `p`/`v`, `ODOMETRY` supplies `P`. If a given PX4
build does not populate valid `ODOMETRY` covariance, the agent falls back to a
fixed conservative diagonal `DEFAULT_P_DIAG` (`agent/mav.py:28`) so the demo
keeps running — meaning `p`/`v` are always real EKF2 estimates, but `P` may be
the fallback. Receivers use `P` as the measurement noise `R` when folding the
packet into their filter.

## Frame and freshness

- **Frame**: NED about the *shared* home origin, so every drone's `p`/`v` live
  in one common frame and peers can be compared directly — no per-drone datum.
- **Freshness**: `own_state()` returns `None` if the latest fix is older than
  `STATE_STALE_S = 2.0 s` (`agent/mav.py:27,189-196`); the broadcaster then
  skips that tick rather than sending stale data
  (`agent/broadcaster.py`, `skipped_no_state`).

## See also

- [UDP bus & wire protocol](03-udp-protocol.md) — the `state` payload schema.
- [State sharing & rate control](04-state-sharing.md) — how often `p`/`v`/`P`
  go out and how that rate is controlled.
- [Kalman prediction](05-kalman-prediction.md) — how a receiver consumes them.
