---
noteId: "df50c9a0814b11f198c7072a98948821"
tags: []

---

# plan2 — richer peer signals: refactor to support all four sharing tiers

**Goal.** Extend the proven p/v/P sharing pipeline so the same idea — *share
sparse, predict the gaps with honest growing uncertainty* — applies to every
PX4 signal class that supports it:

> **Tier 1** — more signals that take the same Kalman treatment (heading,
> battery).
> **Tier 2** — signals that improve the *existing* position filter (trajectory
> intent, mode/landed conditioning).
> **Tier 3** — health/quality signals shared for trust weighting (EKF status,
> GPS quality).
> **Tier 4** — cross-drone *field* estimation, where one drone's data fills
> another's (GPS common-mode bias, barometric reference).

Everything below is grounded in an **empirical survey of the pinned PX4
v1.15.4 SIH SITL (2026-07-16, live in-flight)**: every message this plan
consumes was verified present with real data; wind (`WIND_COV`) was verified
absent on the SIH quad and is excluded. The survey tooling itself becomes part
of the repo (P0).

**Unchanged principles** (from PLAN.md — these are constraints, not
preferences):

- Data path stays **peer-to-peer** on the state channel; C2 remains a thin
  observer/commander, never a data broker.
- All inter-tool data stays **plain UDP**, single-line JSON, validated at
  every receive boundary.
- **The share rate remains the only runtime knob.** New signal sections ride
  the existing state datagram; slow sections decimate by a compile-time
  constant, not a new runtime control.
- PX4 internals stay untouched: every new signal is a **read-only**
  `SET_MESSAGE_INTERVAL` stream request, the same mechanism `agent/mav.py`
  already uses. No EKF2/GPS parameter changes.

---

## 1. Signal catalog (verified sources → tiers)

| Tier | Signal | MAVLink source (verified rate) | Fill model at receiver |
|---|---|---|---|
| 1 | Heading `yaw` + yaw rate | `ODOMETRY` quat + rates + attitude covariance (50 Hz, **already received** by `agent/mav.py`; attitude var diag verified populated at pose_covariance[15/18/20]) | wrap-aware 1-axis CV filter `[yaw, yaw_rate]` |
| 1 | Battery SoC + voltage | `BATTERY_STATUS` (0.5 Hz default, requestable; SIH simulates discharge; `time_remaining` unpopulated — prediction is real work) | 1-axis CV ramp `[soc, drain_rate]` — existing `models.cv_*` with `dims=1` |
| 2 | Trajectory intent | `POSITION_TARGET_LOCAL_NED` (10 Hz default, `type_mask=0`: full smoothed p+v+**a** feed-forward; `yaw` field arrives unwrapped — ignored) | acceleration feed-forward `u` in the position filter's predict step, age-decayed |
| 2 | Mode / armed / landed | `HEARTBEAT` (already parsed) + `EXTENDED_SYS_STATE.landed_state` (5 Hz) | hold-with-age + **model switch**: on-ground ⇒ clamp v=0, near-zero Q growth |
| 3 | EKF health | `ESTIMATOR_STATUS` (1 Hz; flags + vel/pos/mag test ratios verified) | hold-with-age; receiver scales measurement noise R |
| 3 | GPS quality | `GPS_RAW_INT` fix/sats/eph/epv (8 Hz) | hold-with-age; feeds the same R scaling |
| 4 | GPS common-mode bias | `GPS_RAW_INT` lat/lon/alt − fused `p`, converted to NED via `HOME_POSITION` (both verified) | shared 3-D random-walk bias filter over all peers' residuals |
| 4 | Baro reference offset | `SCALED_PRESSURE.press_abs` (1 Hz) | same field estimator, 1-D |

Excluded with reasons: `WIND_COV` (verified absent — EKF2 wind states need an
airspeed sensor or drag-fusion parameter changes, which would touch PX4
internals); full quaternion attitude filtering (top-down demo needs heading
only; roll/pitch of a quad are small and add an error-state MEKF for no
visible payoff); `TERRAIN_REPORT`/`ESC_STATUS`/`RC_CHANNELS`/
`UTM_GLOBAL_POSITION` (verified absent). The SIH rangefinder
(`DISTANCE_SENSOR`, verified working) and a collaborative terrain grid are
future `field` extensions, not this plan (§10).

---

## 2. Wire schema v2 (`common/msg.py`)

The v1 `state` payload (`p`, `v`, `P`) is untouched and stays mandatory — a
v2 packet is a v1 packet with **optional sections**. The current validator
already ignores unknown keys, so v1 and v2 agents interoperate in a mixed
fleet; each section is validated *iff present*.

```json
{"ch":"state","id":2,"seq":417,"t":1752651123.481,
 "p":[3.1,-39.9,-35.0],"v":[4.2,0.3,0.0],
 "P":[0.11,0.11,0.05,0.02,0.02,0.01],

 "yaw":1.761,"w":0.108,"Py":0.0004,                     [T1, every packet]
 "tgt":{"p":[3.4,-41.2,-35.0],"v":[4.8,0.1,0.0],
        "a":[-0.9,-4.1,0.0]},                           [T2, every packet]
 "st":{"mode":"OFFBOARD","armed":true,"lnd":2},         [T2, every packet]

 "bat":{"soc":60.5,"vdc":15.3},                         [T1, decimated]
 "hl":{"flags":895,"vr":0.19,"phr":0.07,
       "fix":3,"sats":10,"eph":0.7},                    [T3, decimated]
 "env":{"res":[0.4,-0.2,0.1],"prs":100551.4}}           [T4, decimated]
```

- `yaw` [rad, wrapped to (−π, π]], `w` = yaw rate [rad/s], `Py` = yaw variance
  [rad²] from ODOMETRY attitude covariance (fallback constant if absent,
  mirroring today's `DEFAULT_P_DIAG` pattern).
- `tgt.a` is the controller's acceleration feed-forward; `tgt.p/v` ride along
  for display and future models.
- `st.lnd` is the raw `MAV_LANDED_STATE` enum (1 = ON_GROUND, 2 = IN_AIR).
- `env.res` = (raw GPS in NED) − (fused `p`), the sender's own GPS residual.
- **Decimation**: slow sections attach when `seq % STATE_SLOW_EVERY == 0`
  *or* the share period ≥ `STATE_SLOW_MIN_PERIOD_S` (defaults 5 and 2.0 in
  `common/config.py`) — so at 5 Hz slow data flows at 1 Hz, and at ≤ 0.5 Hz
  every packet carries everything.
- Size budget: worst-case full packet ≈ 400 B vs ~150 B today — still trivial
  against `MAX_DATAGRAM` and still a *measured demo metric*, not a problem.

**Telemetry v2** (same file): own state gains `yaw`, `bat`, `hl`; each peer
estimate gains `yaw_hat`, `sigma_yaw`, `bat_hat`, `sigma_bat`, `mode`,
`ff` (bool: intent feed-forward active). New optional top-level `field`
object: `{bias:[3], sigma:[3], n_peers, baro_off, sigma_baro}`.

Builders `make_state`/`make_telemetry` grow keyword-only optional args;
existing call sites keep working during the migration.

---

## 3. `kalmanlib/` refactor — generalize without breaking the core

The filter core stays pure functions; nothing existing changes behavior.

1. **`kf.predict` gains an optional control input** —
   `predict(x, P, F, Q, B=None, u=None)` with `x' = Fx + Bu`. Omitted ⇒
   byte-identical to today. `models.cv_B(dt, dims)` supplies the standard
   input matrix `[[dt²/2·I],[dt·I]]`.
2. **`kalmanlib/angles.py`** (new, tiny): `wrap_pi(a)`, `ang_diff(a, b)` —
   the only angle math, unit-tested at the wrap boundary.
3. **`kalmanlib/scalar_cv.py`** (new): `ScalarCvTracker` — a `[x, ẋ]`
   filter over the existing `cv_F/cv_Q/cv_H` with `dims=1`, optional
   `wrap=True` (innovation via `ang_diff`, state re-wrapped after update).
   One class serves both yaw and battery; battery uses a much smaller
   `sigma_a` (SoC drain drifts slowly) — both defaults in `config.py`
   (`SIGMA_YAW_ACC`, `SIGMA_SOC`).
4. **`kalmanlib/peer_state.py`** (new): `PeerState` composes the channels for
   one peer — `kin` (the existing 6-state `PeerTracker`, unchanged math),
   `yaw`, `bat` (ScalarCvTrackers), plus discrete holds (`mode`, `lnd`,
   `hl`, each value + timestamp). `on_packet` routes sections; sections may
   be absent (decimation, v1 peers) and each channel keeps its own last-seq
   independence. `predict(t)` returns a composite estimate.
5. **Tier 2 hooks inside `PeerState`:**
   - *Intent feed-forward*: latest `tgt.a` is stored with its packet time;
     predict-only queries pass `u = tgt.a · max(0, 1 − age_mid/FF_DECAY_S)`
     (`FF_DECAY_S = 2.0`) through the new `B,u` path. Q is **not** reduced —
     intent improves the predicted mean, the honesty envelope stays. `a=0`
     or stale intent ⇒ exactly today's CV.
   - *Landed conditioning*: if last known `lnd == ON_GROUND`, `predict`
     clamps velocity to 0 and substitutes `SIGMA_A_GROUND = 0.05 m/s²` in Q —
     a parked peer's circle stops ballooning, honestly.
   - *Trust weighting (T3)*: measurement update scales R by
     `r_scale(hl)`: 1.0 when all test ratios < 0.5 and `fix ≥ 3`;
     ×4 when any ratio ∈ [0.5, 1); ×10 when any ratio ≥ 1 or `fix < 3`.
     Piecewise, documented, config-overridable.
6. **`kalmanlib/field_bias.py`** (new, T4): `FieldBiasEstimator(dims)` — one
   random-walk bias state `b` (Q = `SIGMA_FIELD_WALK²·dt·I`), updated by each
   arriving peer residual with R from the sender's `eph/epv` + reported `P`.
   Used with `dims=3` for GPS common-mode and `dims=1` for baro offset
   (measurement = sender `prs` − own `prs`, converted to metres). Every agent
   runs its own instance (peer-to-peer purity); C2 only displays what
   telemetry reports.
7. `peer_tracker.py` is untouched except for docstring pointers —
   `PeerTrackerBank` keeps working until `agent/tracker_io.py` switches to a
   `PeerStateBank` in P4, then remains as the `kin` channel's engine.

---

## 4. `agent/` refactor

**`mav.py` splits** (it would pass 400 lines otherwise; style rule: many
small files):

- `agent/mav_client.py` — connection, heartbeat, command helpers,
  `set_message_interval`, param overlay (moved verbatim).
- `agent/mav_signals.py` — all `_on_<msg>` handlers assembling an immutable
  own-state snapshot dict. New handlers, all from the verified survey:
  `BATTERY_STATUS` (1 Hz req), `ESTIMATOR_STATUS` (2 Hz), `EXTENDED_SYS_STATE`
  (2 Hz), `POSITION_TARGET_LOCAL_NED` (default 10 Hz), `GPS_RAW_INT` (default
  8 Hz), `HOME_POSITION` (0.2 Hz), plus wider `ODOMETRY` extraction (quat →
  yaw via atan2, body rates → yaw rate, attitude variance diag).
- `agent/mav.py` remains as a thin facade (`MavClient` keeps its public API:
  `own_state()`, commands) so `flight.py`, `main.py`, tests don't churn.

Snapshot additions to `own_state()`: `yaw, w, Py, bat, hl, lnd, tgt,
gps_res` — each with its own staleness horizon (a stale `tgt` becomes `None`
rather than poisoning peers; core p/v staleness rule unchanged).

GPS residual math (in `mav_signals.py`): equirectangular NED conversion of
`GPS_RAW_INT` about `HOME_POSITION` (adequate at demo scale, documented),
minus fused `p`. Optional `AIRKAL_DEMO_GPS_BIAS="2.0,-1.5,0.0"` env adds a
known offset to the *shared residual only* — a labeled demo injection that
gives Tier 4 a visible, known-truth signal (SIH instances have independent
GPS noise, so the natural common mode is ≈ 0; the estimator honestly finding
"≈ 0 ± shrinking σ" is correct but undramatic). Never touches PX4.

**`broadcaster.py`**: `tick()` packs v2 sections from the snapshot with the
decimation rule (§2). Rate logic untouched — still the only knob.

**`tracker_io.py`**: routes decoded packets into `PeerStateBank` +
`FieldBiasEstimator`s; `estimates()` emits the extended telemetry shape.

**`main.py`**: telemetry builder gains the new fields; wiring otherwise
unchanged.

---

## 5. `c2/` + `web/`

- **`c2/errors.py`** generalizes from one hardcoded comparison to named
  channels sharing the nearest-in-time machinery (30 s history, 1 s
  tolerance): `pos` (existing), `yaw` (via `ang_diff`, degrees for display),
  `bat` (SoC points). Same "C2 computes no filter, only compares what agents
  report" property.
- **FleetStore/WS snapshot**: passes the new telemetry fields and the
  `field` object through; no new state kept.
- **Web page** (`web/`):
  - fleet table: battery column `pred ±σ` (observer's estimate of each peer)
    next to the peer's own report, mode/landed badge, EKF-health dot
    (green/amber/red from `hl`).
  - map: short heading arrow on every true position; the observer's predicted
    peers get a predicted-heading arrow; landed peers render with a frozen
    (non-breathing) circle.
  - charts: the prediction-error chart gains a channel selector
    (pos / yaw / battery); new small "field" panel: GPS common bias `b̂ ±σ`
    per axis and baro offset, converging as packets arrive.
  - controls: **unchanged** — the rate slider stays the only knob.

---

## 6. Config additions (`common/config.py`)

```
STATE_SLOW_EVERY = 5            # decimation for bat/hl/env sections
STATE_SLOW_MIN_PERIOD_S = 2.0   # at slow rates every packet carries all
FF_DECAY_S = 2.0                # intent feed-forward age decay
SIGMA_YAW_ACC = 0.5             # yaw-rate white noise [rad/s^2]
SIGMA_SOC = 0.02                # SoC drain drift [%/s^2]
SIGMA_A_GROUND = 0.05           # landed-peer process noise [m/s^2]
R_SCALE_DEGRADED = 4.0          # trust weighting steps
R_SCALE_FAILING = 10.0
SIGMA_FIELD_WALK = 0.05         # field bias random walk [m/s^0.5]
```

All env-overridable via the existing `_env_*` helpers where useful. No new
runtime commands, no new UDP channels, no new ports.

---

## 7. Build order (phases, each independently shippable & verifiable)

**P0 — survey tooling (≈0.5 d).**
Promote the survey probe to `scripts/survey_mav.py` (passive listen → request
candidates → availability table); add `make survey`. Extend
`scripts/verify_sitl.py` to also assert presence of `BATTERY_STATUS`,
`ESTIMATOR_STATUS`, `EXTENDED_SYS_STATE`, `POSITION_TARGET_LOCAL_NED`,
`GPS_RAW_INT`, `HOME_POSITION`.
*Acceptance: `make verify` passes on 3 instances with the extended checks;
`make survey` reproduces the availability table.*

**P1 — wire schema v2 (≈0.5 d).**
`common/msg.py` optional-section validators + builder extensions; config
constants. TDD first: round-trip per section, absent-section pass, malformed
section rejected, v1 packet still validates, size budget test.
*Acceptance: schema tests green; existing suite untouched-green (91 tests).*

**P2 — kalmanlib generalization (≈1 d).**
`kf.predict(B,u)`, `models.cv_B`, `angles.py`, `scalar_cv.py`,
`field_bias.py`, `peer_state.py` with landed/trust/intent hooks. TDD:
golden 1-D control-input solution; `u=None` bit-equivalence with today;
yaw-wrap goldens across ±π; battery ramp convergence; NEES consistency for
`PeerState.kin` with and without intent (intent must not break consistency);
`r_scale` table; field-bias convergence to a known injected bias with σ
shrinking ~1/√N.
*Acceptance: kalmanlib coverage ≥ 90%; all invariants above proven by tests.*

**P3 — agent signal extraction (≈1 d).**
`mav.py` → `mav_client.py`/`mav_signals.py` split (facade preserved); new
handlers; snapshot v2; per-signal staleness. Unit tests with synthetic
pymavlink message stubs (no SITL needed), plus the P0 live verify.
*Acceptance: against a live SITL, a debug dump of `own_state()` shows all new
fields live within 5 s of connect; existing agent tests green.*

**P4 — Tier 1 on the wire, end to end (≈1 d).**
Broadcaster packs `yaw/w/Py` + decimated `bat`; `tracker_io` switches to
`PeerStateBank`; telemetry v2; C2 pass-through; minimal web columns
(battery, heading arrows). Mixed-fleet test: a v1-shaped packet (no
sections) still drives the `kin` channel.
*Acceptance (3-drone orbit): at 0.2 Hz share, observer mid-gap yaw error
< 5° (orbit yaw rate is only 6°/s — CV on yaw is strong material); battery
prediction between decimated updates within 1 SoC point; `pos` error
behavior unchanged from today at every rate.*

**P5 — Tier 2: intent + conditioning (≈1 d).**
`tgt`/`st` sections flow; feed-forward and landed clamp active in
`PeerState`; `errors.py` channel generalization lands here for measurement.
*Acceptance (the headline number): at 0.2 Hz share during orbit turns, the
`pos` prediction error with intent is **≥ 3× lower** than the recorded
CV-only baseline (same run config, measured by C2's error tracker); after
`land`, every observer's σ for the landed peer stays < 0.5 m through 60 s of
silence instead of ballooning.*

**P6 — Tier 3: trust weighting (≈0.5 d).**
`hl` section flows; R scaling active; web health dots + fleet-health panel.
SITL has no natural fault injection, so the acceptance is unit-level plus a
replay test: feeding a recorded packet stream with `hl` ratios artificially
raised shows the receiver's R scaling and slower covariance collapse.
*Acceptance: replay test demonstrates ×4/×10 R scaling end-to-end through
`PeerState`; UI reflects health.*

**P7 — Tier 4: field estimation (≈1.5 d).**
`env` section flows; per-agent `FieldBiasEstimator` (GPS 3-D + baro 1-D);
telemetry `field` object; web field panel.
*Acceptance: with `AIRKAL_DEMO_GPS_BIAS="2.0,-1.5,0.0"` on all agents, every
agent's estimated bias converges to (2.0, −1.5, 0) within ±0.3 m and σ
visibly shrinks as drones join; with the injection off, estimate stays ≈ 0
with honest σ — both runs scripted into the smoke path.*

**P8 — docs, runbook, polish (≈1 d).**
Update `design/03-udp-protocol.md` (schema v2 table), `04a` (new provenance
rows), `05` (channels, intent, conditioning); new `design/04b-signal-catalog.md`
(the §1 catalog + survey method); web design-tab picks them up automatically
via the existing `/api/design`. Extend `scripts/smoke.sh`: assert v2 sections
observed on the wire and the P5/P7 numbers. Demo runbook v2 (§9).

Total ≈ **8 working days**. Order is deliberate: schema → math → extraction →
wire, so every phase ships green and a stop after any phase leaves a working
system.

---

## 8. Testing

- **Unit (TDD; coverage gate extends to the new kalmanlib modules, ≥80%
  overall as today):** listed per-phase above; the invariants that matter —
  `u=None` equals today's predict bit-for-bit; wrap correctness at ±π;
  NEES consistency preserved with intent on; landed clamp bounds σ;
  `r_scale` piecewise table; field bias converges with √N shrink; schema v1
  compatibility.
- **Integration (no browser):** mixed v1/v2 fleet packet handling; decimation
  schedule vs rate; replay-driven trust weighting; smoke.sh extended to grep
  v2 sections off the wire with `socat`, mirroring how it checks state today.
- **Demo acceptance** = the P4/P5/P7 numeric criteria via the §9 runbook,
  measured by C2's own error tracker (end-to-end, not staged).

---

## 9. Demo runbook v2 (delta over PLAN.md §9)

```bash
make run N=3          # unchanged lifecycle
# browser:
#  1. Start pattern; note heading arrows and battery ±σ columns.
#  2. Slide to 0.2 Hz: position circles breathe as before; yaw arrows keep
#     tracking through the orbit; battery predictions ramp between updates.
#  3. Error chart, channel = pos: toggle the intent overlay run (P5 baseline
#     comparison) — turns no longer spike the error.
#  4. Land one drone: its circle freezes small instead of ballooning.
#  5. Field panel: watch GPS common-bias converge (with the demo injection
#     env set, it converges to the known truth).
make down
```

---

## 10. Risks & chosen defaults

| Risk / decision | Position |
|---|---|
| Stale intent misleads prediction | Feed-forward decays to zero over `FF_DECAY_S = 2 s`; Q never reduced; `tgt` staleness-gated sender-side too |
| `POSITION_TARGET_LOCAL_NED.yaw` arrives unwrapped (verified, e.g. 890.6) | Field ignored; heading comes only from ODOMETRY |
| Attitude covariance absent on some builds | Same fallback pattern as today's `DEFAULT_P_DIAG`: fixed conservative `Py` |
| Yaw wrap bugs | All angle math confined to `angles.py`; golden tests at the boundary |
| Packet growth | Worst case ≈ 400 B, decimated; bytes/s remains a displayed metric — the bandwidth story gets *richer*, not worse |
| SIH battery only drains meaningfully in flight | Battery demo criteria measured during orbit; on ground SoC is static (correctly predicted static) |
| Natural GPS common-mode ≈ 0 across independent SIH instances | Honest ≈ 0 result kept; labeled `AIRKAL_DEMO_GPS_BIAS` injection (agent-side, never PX4) provides the known-truth visible demo |
| Mixed v1/v2 fleet during rollout | Sections optional; every channel degrades to exactly today's behavior when its section is absent |
| Scope creep inside kalmanlib | CV stays the only kinematic model; intent is an *input* to CV, not a new model — CA/CT/IMM remain out of scope |

## 11. Explicitly out of scope (future work)

Full quaternion/error-state attitude filtering; wind field (source verified
absent on SIH); collaborative terrain grid from the (verified working) SIH
rangefinder — a natural third `field_bias.py` client once a grid
representation exists; event-triggered sending; consuming any peer estimate
in a control loop; binary packing. The v2 schema (optional sections,
per-channel independence) is designed so each of these bolts on without
another wire change.
