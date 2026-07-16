---
noteId: "ee046790813211f198c7072a98948821"
tags: []

---

# Kalman prediction

Every agent keeps one small Kalman filter **per peer**
(`kalmanlib/peer_tracker.py`). The filters are what make a 0.2 Hz data feed
usable: between packets they predict, and their covariance grows to say how
much the prediction can be trusted.

## The model

Constant-velocity (CV) in 3 NED dimensions, state `[p, v]` (6 elements),
with the standard white-noise-acceleration process noise
(`kalmanlib/models.py`):

```
F(dt):  p' = p + v·dt,  v' = v

Q(dt) per axis = sigma_a² · [[dt⁴/4, dt³/2],
                             [dt³/2, dt²  ]]
```

`sigma_a = 3 m/s²` is the demo default. CV is *deliberately* the only model —
the drones fly a circular orbit, so the model is honestly imperfect during
turns and the prediction error is real, not staged. Richer models (CA/CT/IMM)
are out of scope by design.

The filter core (`kalmanlib/kf.py`) is pure functions — no hidden state,
inputs untouched, new `(x, P)` returned every call. The measurement update
uses the **Joseph form**, which keeps the covariance symmetric positive
semi-definite under floating-point roundoff.

## Feeding the filter

On each received `state` packet from peer *i* (`PeerTracker.on_packet`):

1. **First packet**: initialize `x` from the packet's `[p, v]` and `P` from
   its reported covariance diagonal.
2. **After that**: predict from the last update time to the packet's
   timestamp `t`, then update with the packet as a full-state measurement.
   The measurement noise `R` is the **sender's own reported EKF covariance
   diagonal** (floored at 1e-4 so an all-zero report cannot go singular) —
   the receiver trusts each packet exactly as much as its sender does.
3. **Out-of-order or duplicate packets** (by `seq`, then by `t`) are dropped
   and counted, never applied.

## Querying between packets

`PeerTracker.predict(t_query)` returns a **predict-only** estimate at any
time without touching the stored state:

- position and velocity extrapolated by the CV model,
- covariance grown by `Q(age)` — the longer the silence, the bigger it gets,
- `sigma` = RMS of the position variance diagonal — a single "1σ radius" [m],
- `age` = time since the last accepted packet.

This is the property the demo shows: the estimate is **continuous** in time
regardless of the share rate, with an uncertainty that grows during silence
and snaps back down on every arrival.

## How you see it on the front page

- **Map**: the observer's `✕` marks are its predicted peer positions; the
  `◯` circles are 1σ and 2σ of that prediction. Lower a drone's share rate
  and watch its circles breathe — grow, snap, grow, snap.
- **Prediction error chart**: for every observer/peer pair, C2 compares the
  observer's telemetry-reported prediction against the peer's own reported
  position, aligned nearest-in-time (see [C2 server](06-c2-server.md)).
  During straight-ish flight the CV prediction is good even at low rates;
  in the turns of the orbit it degrades — visibly and honestly.
- **Consistency**: `kalmanlib/kf.py` also provides NIS (normalized
  innovation squared), used by the test suite to verify the filter is
  statistically consistent, not just plausible-looking.
