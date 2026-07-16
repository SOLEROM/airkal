---
noteId: "13970470813511f198c7072a98948821"
tags: []

---

# Kalman filter — effective calculation methods on embedded low-power CPUs

A research report on how to make Kalman-type filters cheap enough for
microcontroller-class processors, and what mature implementations (PX4 EKF2,
Skydio's SymForce pipeline, embedded EKF libraries) actually do. Findings are
grounded in the sources listed at the end; confidence labels follow each claim
where it matters. Relevance to airkal's own `kalmanlib/` per-peer filter is
called out in the last section.

## Where the cycles go

A textbook Kalman step is dominated by dense matrix work: the covariance
prediction `P = FPFᵀ + Q` is O(n³) in the state dimension, and the update
requires inverting the innovation covariance `S = HPHᵀ + R`. Matrix inversion
is the worst offender on small CPUs — it cannot be parallelized well, scales
poorly, and must run online every step (confidence: high — multiple sources).
Everything below is a way to shrink or dodge those two operations.

## The effective methods, ranked by leverage

### 1. Shrink the state — decompose coupled systems

The cheapest multiply is the one you never do. Valade et al. (Sensors, 2017)
measured a **3.7× complexity reduction** by splitting one coupled filter into
uncoupled subsystems, and rank this as the first optimization to reach for
(confidence: high). If `F`, `Q`, `H`, `R` are block-diagonal, an n-state filter
decomposes into k independent small filters, and O(n³) work becomes
k·O((n/k)³) — e.g. one 6-state filter → three 2-state filters is ~9× less
matrix work.

### 2. Sequential scalar measurement updates — never invert a matrix

If `R` is diagonal (independent measurement noise), process measurements **one
scalar at a time**: each update needs only a scalar division instead of an
m×m inversion of `S`. This is standard practice in embedded navigation and is
the core of Bierman's algorithm (confidence: high). PX4's EKF2 fuses each
observation type — and in places each axis — as separate updates for exactly
this reason. If `R` has cross-correlations, diagonalize it once offline.

### 3. Exploit known sparsity in F, H, Q

Generic `matmul(F, P)` wastes cycles multiplying by the zeros and ones of a
structured model. For a constant-velocity model, `FPFᵀ` collapses to a handful
of scalar adds/multiplies per axis. Two ways to get this:

- **Hand-expand** the equations for small fixed models (classic approach).
- **Symbolic code generation**: PX4 EKF2 derives its covariance prediction and
  measurement Jacobians symbolically (originally MATLAB symbolic toolbox, now
  **SymForce**) and emits flattened, branchless C++ with common-subexpression
  elimination and zero dynamic allocation. SymForce reports **~10× speedups
  over standard autodiff** from flattening and sparsity exploitation
  (confidence: medium — vendor-reported, but production-proven at Skydio and
  in PX4).

### 4. Constant (steady-state) gains — the alpha-beta endpoint

For a time-invariant model with fixed dt, the Kalman gain `K` converges to a
steady state quickly; after that the CPU is wasting cycles recomputing it.
Options, in increasing savings (confidence: high):

| Technique | What still runs online | Cost |
|---|---|---|
| Full KF | predict + gain + update | O(n³) per step |
| Precomputed gain schedule (LUT) | predict + update with stored K | no online inversion |
| Steady-state Kalman / **alpha-beta filter** | state recursion only, fixed α, β | a few multiplies per axis |

The alpha-beta filter *is* the steady-state Kalman filter for a
constant-velocity model when its coefficients are derived from the noise
ratios — same tracking quality at steady state, a fraction of the arithmetic.
The trade: no covariance output, so no innovation gating and no honest
uncertainty during transients or after signal gaps.

### 5. Factored covariance — UD / square-root filters for numerical safety

The standard covariance update `P = (I − KH)P` loses symmetry and positive
definiteness under rounding, which on long-running embedded filters ends in
divergence ("covariance blow-up"). Two defenses:

- **Joseph stabilized form** — costs more multiplies but keeps `P` symmetric
  positive-definite; this is what PX4 EKF2 uses, in **single precision
  throughout** with first-order covariance approximations to cut load
  (confidence: high).
- **UD factorization (Bierman–Thornton)** — store `P = UDUᵀ`, propagate with
  Thornton's algorithm, update with Bierman's scalar algorithm. Symmetry and
  positive-definiteness hold *by construction*, square roots are avoided
  entirely, and measurement processing is naturally sequential-scalar. The
  method of choice when word length is short (16–32 bit) or the filter runs
  for days (confidence: high).

### 6. Arithmetic choices: single float on FPU, fixed-point only when forced

- On Cortex-M4F/M7-class parts with an FPU, **single-precision float is the
  standard** — the FPU removes the software-float penalty and 32-bit precision
  suffices when combined with Joseph form or UD (confidence: high; this is
  PX4's configuration).
- **Fixed-point (Q-format)** only pays on FPU-less cores (Cortex-M0/M0+).
  Converting a float algorithm to fixed point is error-prone and reportedly
  consumes ~30% of development time, with quantization effects that interact
  badly with covariance math (confidence: medium). Prefer a factored filter in
  software float before resorting to fixed point.
- **CMSIS-DSP** provides vectorized kernels (Helium/Neon where available) for
  the matrix primitives if a generic-matrix implementation is kept.

## What it costs in practice — measured numbers

| Platform | Filter | Time per step |
|---|---|---|
| Teensy 4.0, Cortex-M7 @ 600 MHz, FPU | 2-state EKF (pendulum) | 14–15 µs (single/double) |
| Teensy 4.0, Cortex-M7 @ 600 MHz, FPU | 4-state EKF (IMU) | 86–107 µs |
| STM32L053, Cortex-M0+ @ 32 MHz, no FPU | 2D-orientation EKF | 1.18 ms → 3.8 % CPU at 26 Hz |
| ATMega328, 8-bit @ 16 MHz | ~100 kFLOPS available | feasible only for tiny states |

(Sources: pronenewbits Embedded_EKF_Library benchmarks; Valade et al. 2017.)
Takeaway: small-state Kalman filters are comfortably real-time even on an
FPU-less M0+ — the techniques above matter as state count grows (cost is
cubic) or when the power budget, not the deadline, is the constraint.

## Reference implementations worth reading

- **TinyEKF** (simondlevy) — header-only C/C++, static allocation only,
  compile-time state/observation sizes, single or double precision; Arduino /
  Teensy / STM32. Good minimal baseline.
- **Embedded_EKF_Library** (pronenewbits) — readability-first EKF for
  Teensy 4 / STM32, no malloc, no Eigen/STL; source of the benchmark rows
  above.
- **PX4 ECL/EKF2** — the production pattern: single precision, sequential
  fusion, Joseph stabilized updates, SymForce-generated covariance code.
- **SymForce** (Skydio) — symbolic derivation → flattened branchless C++ with
  CSE, templated Eigen, zero dynamic allocation.

## What this means for airkal's `kalmanlib/`

airkal's per-peer tracker (`kalmanlib/peer_tracker.py`) is a 6-state
constant-velocity filter with position-only measurements and NIS gating,
currently in NumPy on a full-size CPU — cost is a non-issue today. If it ever
moves onto a companion MCU or a flight controller, the playbook falls straight
out of the table above:

1. **Decompose per axis** (method 1): `cv_F`/`cv_Q`/`cv_H` are block-diagonal
   per axis, so the 6-state filter is exactly three independent 2-state
   filters — ~9× less matrix work, no behavior change.
2. **Scalar updates** (method 2): position measurements per axis are scalar,
   so `S` is 1×1 and inversion is a single division — the NIS gate survives
   unchanged as a scalar test.
3. **Steady-state gains** (method 4) only if covariance output stops
   mattering — airkal *uses* `P` (staleness/uncertainty per peer), so a full
   (or UD) filter is worth keeping; alpha-beta would forfeit that.
4. **Single-precision float + Joseph or UD form** (methods 5–6) once the
   filter runs unattended for long missions.

## Open questions

- No independent (non-vendor) benchmark of SymForce-generated filter code vs
  hand-optimized C on Cortex-M was found; the ~10× figure is vs autodiff, not
  vs hand-written code.
- Concrete energy-per-update (µJ) measurements for KF variants on modern
  low-power parts (STM32U5, Ambiq) were not found — literature reports time
  and FLOPs, not joules.
- The Al-Jlailaty & Mansour attitude-estimator survey (arXiv 2012.04075)
  likely contains cycle-level comparisons; the PDF was not machine-readable in
  this pass and is worth a manual read.

## Sources

- Valade, Acco, Grabolosa, Fourniols — *A Study about Kalman Filters Applied
  to Embedded Sensors*, Sensors, Dec 2017.
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC5751614/>
- *A summary on the UD Kalman Filter* (Thornton/Bierman methods), arXiv, 2022.
  <https://arxiv.org/abs/2203.06105>
- PX4 documentation — *Using PX4's Navigation Filter (EKF2)*.
  <https://docs.px4.io/main/en/advanced_config/tuning_the_ecl_ekf>
- SymForce — Skydio, symbolic computation & codegen (paper arXiv 2204.07889).
  <https://github.com/symforce-org/symforce>
- TinyEKF — Simon D. Levy. <https://github.com/simondlevy/TinyEKF>
- Embedded_EKF_Library — pronenewbits (Teensy/STM32 benchmarks).
  <https://github.com/pronenewbits/Embedded_EKF_Library>
- *Reconciling steady-state Kalman and alpha-beta filter design*, IEEE.
  <https://ieeexplore.ieee.org/document/62250/>
- Al-Jlailaty, Mansour — *Efficient Attitude Estimators: A Tutorial and
  Survey*, arXiv, Dec 2020. <https://arxiv.org/abs/2012.04075>
- ARM CMSIS-DSP. <https://github.com/ARM-software/CMSIS-DSP>
