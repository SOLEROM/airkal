---
noteId: "84af4ec0813411f198c7072a98948821"
tags: []

---

# Kalman filtering in drones and robotics — a value report

airkal leans on the Kalman filter in two very different places: PX4's **EKF2**
produces each drone's own fused state, and a small **per-peer constant-velocity
filter** (`kalmanlib/`) reconstructs where the *other* drones are between shared
packets. This page steps back from the code and asks the wider question —
**what value does Kalman filtering actually deliver in drones and robotics, and
why is it the right tool for what airkal does?** The claims below are grounded
in current (2020–2026) literature; sources are listed at the end.

## The core value, in one breath

A Kalman filter turns a stream of **noisy, imperfect, intermittent** sensor
readings into a **single best estimate plus an honest statement of how much to
trust it** — recursively, in constant memory, producing an answer on *every*
tick even when the measurements don't arrive. Four properties fall out of that,
and every one of them earns its keep in a flying robot:

| Property | What it buys a drone |
|---|---|
| **Optimal fusion** | Combines GPS + IMU + baro + vision into one estimate better than any single sensor — the flight controller reads reliable state from parts that are each individually wrong. |
| **Estimate *and* covariance** | You get the number *and* its uncertainty. Downstream logic can gate, reject, or wait based on how confident the filter is — not guess. |
| **Predict through gaps** | The predict step runs whether or not a measurement showed up. Late GPS, a dropped frame, a paused feed — the estimate keeps advancing, degrading gracefully instead of vanishing. |
| **Recursive & cheap** | Fixed cost per step, no growing history buffer. It runs at kHz on a flight controller and at Hz on a laptop with the same code shape. |

That third property is the one airkal is built around, so it's worth stating
sharply: **because a Kalman estimate carries velocity and a growing covariance,
a receiver can coast a peer forward through long silences and still know how
wrong it might be.** That is what turns the inter-drone *share rate* into a free
knob rather than a hard requirement.

## The value in numbers

The field has measured this repeatedly:

- **Sensor fusion is the default, not a nicety.** Across recent UAV work the
  EKF (and its UKF cousin) is *the* preferred estimator for fusing IMU,
  magnetometer, barometer, GNSS, optical flow, LiDAR and RGB-D into position
  and attitude — including for GPS-denied flight where GNSS is fused with
  visual-inertial odometry only when it's trustworthy.
- **Variant choice is an accuracy-vs-compute dial.** A representative
  inertial-navigation comparison found the most accurate sigma-point filter cut
  height error by ~**96 %** and pitch error by ~**77 %** versus a plain linear
  KF — but at roughly **9.6×** the compute. The multiplicative EKF sat in the
  middle and is described as the one "widely used in engineering" precisely
  because of its accuracy-to-cost ratio. **More filter is not automatically
  better; you buy accuracy with cycles.**
- **Graceful degradation is a documented failure mode, not a given.** Naïve
  filters *diverge* when measurements go intermittent; the value of a
  well-formed filter (right process noise, honest covariance growth) is that it
  **degrades smoothly** and recovers the moment a measurement returns. This is
  the whole game for dead reckoning in urban canyons and for tracking through
  detection dropouts.

## Where it shows up in a drone or robot

1. **Attitude & pose** — fuse gyro + accelerometer + magnetometer + baro into a
   drift-free orientation. This is the classic "complementary filter grows up
   into a Kalman filter" story.
2. **Position & velocity** — fuse GNSS with inertial (INS/GPS). When GNSS drops,
   the same filter dead-reckons on IMU, then snaps back on re-acquisition.
3. **GPS-denied navigation** — swap GNSS for VIO, optical flow, LiDAR or
   range-to-anchor; the filter structure is unchanged, only the measurement
   model changes.
4. **Target / object tracking** — a **constant-velocity** filter tracks a
   non-maneuvering target well and is the standard baseline; it degrades
   predictably when the target actually maneuvers (the model mismatch shows up
   as rising innovation, which the covariance reports).
5. **Cooperative / multi-robot localization** — teams fuse each other's pose
   estimates. Because naïvely fusing correlated estimates makes a filter
   over-confident, the field uses **covariance intersection** / split-CIF to
   stay *consistent*, with communication and compute that scale **O(N)** in team
   size.

## The variant landscape — pick by nonlinearity and budget

| Filter | Handles | Cost | Use when |
|---|---|---|---|
| **Linear KF** | linear models, Gaussian noise | lowest | dynamics/measurements are (near-)linear — e.g. a constant-velocity tracker |
| **EKF** | mild nonlinearity via Jacobians | low–moderate | the workhorse; best efficiency-vs-quality trade for most navigation |
| **UKF / sigma-point** | stronger nonlinearity, no Jacobians | moderate–high | attitude and strongly nonlinear models where linearization error bites |
| **Particle filter** | non-Gaussian, multi-modal | high | ambiguous, multi-hypothesis problems (e.g. global relocalization) |
| **Error-state EKF** | attitude on a manifold | low–moderate | INS/GNSS and IMU fusion — PX4's EKF2 is one |

The recurring lesson: **match the filter to how nonlinear the problem really
is.** Reaching for a particle filter or UKF on an essentially linear problem
spends cycles you didn't need to.

## How airkal uses it — two filters, two jobs

airkal is a deliberate, honest example of picking the *right amount* of filter
for each job.

**Own state → PX4 EKF2 (we consume, we do not retune).** EKF2 is a **24-state
error-state EKF**: quaternion attitude, NED velocity and position, gyro/accel
biases, plus optional magnetic-field, wind and terrain states. It fuses GPS,
mag, baro, optical flow, airspeed and range with quality-gated control logic,
propagates covariance with numerically stable (Joseph-style, symbolically
generated) updates, and runs an **output predictor** that forecasts the delayed
filter estimate to *now* for the controller. airkal reads its three products —
position, velocity and the covariance diagonal — straight off MAVLink. **PX4's
internal estimator rates are never touched**; that's PX4's job and it does it
well.

**Peers → per-peer constant-velocity KF (the minimum that works).** Each agent
keeps one tiny CV filter per peer. Between shared packets it runs
**predict-only**, and the covariance **grows with the silence** — the estimate
literally reports its own staleness. When a packet lands, a Joseph-form update
folds it in. A constant-velocity model is the *correct* choice here: peers fly
smooth orbits, the model is near-linear, and a heavier filter would buy nothing.

**The value airkal demonstrates.** Because each shared state carries **velocity
and covariance**, not just a position, a receiver can coast a peer forward for
seconds and still quote a trustworthy uncertainty. So the inter-drone **share
rate becomes a runtime knob**: drop it and bandwidth collapses while the
predicted track stays usable and the growing σ tells you exactly when it stops
being. That is the entire thesis of the demo, and it is *only* possible because
the shared quantity is a filter state, not a raw fix. Note the deliberate
restraint — airkal tracks peers **independently** for display and prediction;
it does **not** fuse peer estimates back into its own navigation, so it sidesteps
the correlation/consistency problem that forces the wider field toward
covariance intersection. Right-sized, not over-built.

## The honest costs

A value report that only lists upside is marketing. The real trade-offs:

- **Model mismatch.** A CV filter lags a hard-maneuvering target; an
  over-confident process model under-reports error. The covariance is only as
  honest as the noise you tuned into it.
- **Tuning burden.** Process- and measurement-noise choices *are* the filter's
  behavior. Get them wrong and you are either sluggish or over-confident.
- **Linearization / distribution assumptions.** The EKF trusts a local linear
  approximation; every Kalman variant assumes Gaussian noise. When neither
  holds, accuracy drops and you pay for a UKF or particle filter.
- **Consistency in teams.** Fusing correlated estimates naïvely makes filters
  lie about their own certainty — the reason cooperative systems need
  covariance intersection, and the reason airkal chooses not to fuse at all.

## Bottom line

For drones and robotics the Kalman filter earns its ubiquity by delivering three
things at once that nothing simpler does: **a fused estimate, a calibrated
uncertainty, and a prediction that survives missing data** — all recursively and
cheaply. Its cost is honesty in modeling and tuning. airkal is a compact
demonstration of using it *well*: lean on PX4's mature EKF2 for own-state, apply
the smallest sufficient filter (constant-velocity) for peers, and let the
covariance turn "we heard from that drone a while ago" into a number you can act
on — which is exactly what lets the share rate become something you can turn
down.

## Sources

- [Kalman Filters and Beyond: A Comprehensive Review of State Estimation Techniques in Robotics, AI, and Complex Dynamic Systems](https://www.researchgate.net/publication/384762080_Kalman_Filters_and_Beyond_A_Comprehensive_Review_of_State_Estimation_Techniques_in_Robotics_Artificial_Intelligence_and_Complex_Dynamic_Systems)
- [Comparison of Kalman Filters for Inertial Integrated Navigation (PMC6470584)](https://pmc.ncbi.nlm.nih.gov/articles/PMC6470584/) — concrete accuracy/compute numbers
- [Evaluation of Localization by EKF, UKF, and Particle-Filter-Based Techniques (Wiley, 2020)](https://onlinelibrary.wiley.com/doi/10.1155/2020/8898672)
- [Sensor Fusion for Drone Position and Attitude Estimation using EKF (2025)](https://www.researchgate.net/publication/393590343_Sensor_Fusion_for_Drone_Position_and_Attitude_Estimation_using_Extended_Kalman_Filter)
- [A multi-sensor fusion-based UAV autonomous localization system (Taylor & Francis, 2025)](https://www.tandfonline.com/doi/full/10.1080/17445760.2025.2602166)
- [SMART-TRACK: Kalman-Filter-Guided Sensor Fusion for Robust UAV Object Tracking (arXiv, 2024)](https://arxiv.org/html/2410.10409v1)
- [A robust cooperative localization algorithm based on covariance intersection for multi-robot systems (PeerJ CS, 2023)](https://peerj.com/articles/cs-1373/)
- [Decentralized Cooperative Localization Using Split Covariance Intersection Filter (IEEE)](https://ieeexplore.ieee.org/document/6816839/)
- [PX4 EKF2 — Extended Kalman Filter architecture (DeepWiki)](https://deepwiki.com/PX4/PX4-Autopilot/2.1-extended-kalman-filter-(ekf2))
- [Using PX4's Navigation Filter (EKF2) — PX4 User Guide](https://docs.px4.io/main/en/advanced_config/tuning_the_ecl_ekf)
