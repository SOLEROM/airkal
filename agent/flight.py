"""Flight driver: makes the demo move.

On pattern_start: offboard warmup → arm → climb to 30 m + 5 m per drone id →
slow orbit (radius 40 m, period 60 s, per-drone phase offset) around the shared
NED origin. Altitude separation means the shared circle is collision-free.
Deterministic motion with real turns — good material for CV prediction and its
honest failure during turns.
"""

import asyncio
import logging
import math
import time

log = logging.getLogger(__name__)

LOOP_HZ = 20.0
WARMUP_S = 1.5              # stream setpoints before requesting offboard
BASE_ALT_M = 30.0
ALT_STEP_M = 5.0
ORBIT_RADIUS_M = 40.0
ORBIT_PERIOD_S = 60.0
TAKEOFF_TOL_M = 1.5
PHASE_STEP_RAD = 2.399963   # golden angle: spreads any N drones evenly-ish

class FlightDriver:
    def __init__(self, mav, drone_id: int):
        self.mav = mav
        self.drone_id = drone_id
        self.phase = "idle"    # idle|warmup|arming|takeoff|orbit|hold|landing
        self.alt_m = BASE_ALT_M + ALT_STEP_M * (drone_id - 1)
        self.phase0 = (drone_id - 1) * PHASE_STEP_RAD
        self._hold_target: list[float] | None = None
        self._theta0 = self.phase0
        self._t_orbit0 = 0.0
        self._t_phase0 = 0.0
        self._last_arm_tx = 0.0

    # ── commands from the C2 channel ─────────────────────────────────────────

    def handle_cmd(self, cmd: str) -> None:
        if cmd == "pattern_start":
            if self.phase in ("idle", "hold"):
                self._enter("warmup")
        elif cmd == "pattern_stop":
            if self.phase in ("takeoff", "orbit"):
                self._hold_target = self._current_target()
                self._enter("hold")
        elif cmd == "land":
            if self.phase != "idle":
                self.mav.set_mode_auto_land()
                self._enter("landing")

    def _enter(self, phase: str) -> None:
        log.info("drone %d: flight phase %s -> %s", self.drone_id, self.phase,
                 phase)
        self.phase = phase
        self._t_phase0 = time.time()

    # ── target computation ───────────────────────────────────────────────────

    def _orbit_target(self, now: float) -> tuple[list[float], float]:
        theta = self._theta0 + 2 * math.pi * (now - self._t_orbit0) / ORBIT_PERIOD_S
        x = ORBIT_RADIUS_M * math.cos(theta)
        y = ORBIT_RADIUS_M * math.sin(theta)
        yaw = theta + math.pi / 2.0    # face along the direction of travel
        return [x, y, -self.alt_m], yaw

    def _current_target(self) -> list[float]:
        own = self.mav.own_state()
        if own is None:
            return [0.0, 0.0, -self.alt_m]
        return list(own["p"])

    # ── main loop ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        period = 1.0 / LOOP_HZ
        while True:
            await asyncio.sleep(period)
            own = self.mav.own_state()
            if own is None or self.phase == "idle":
                continue
            now = time.time()

            if self.phase == "warmup":
                self.mav.send_position_setpoint(own["p"], 0.0)
                if now - self._t_phase0 > WARMUP_S:
                    self.mav.set_mode_offboard()
                    self._enter("arming")

            elif self.phase == "arming":
                self.mav.send_position_setpoint(own["p"], 0.0)
                if own["armed"]:
                    self._takeoff_from = list(own["p"])
                    self._enter("takeoff")
                elif now - self._last_arm_tx > 1.0:
                    self.mav.arm()
                    self._last_arm_tx = now

            elif self.phase == "takeoff":
                target = [self._takeoff_from[0], self._takeoff_from[1],
                          -self.alt_m]
                self.mav.send_position_setpoint(target, 0.0)
                if abs(own["p"][2] + self.alt_m) < TAKEOFF_TOL_M:
                    # enter the orbit at the angle nearest the climb-out point
                    x, y = own["p"][0], own["p"][1]
                    self._theta0 = (math.atan2(y, x)
                                    if math.hypot(x, y) > 1.0 else self.phase0)
                    self._t_orbit0 = now
                    self._enter("orbit")

            elif self.phase == "orbit":
                target, yaw = self._orbit_target(now)
                self.mav.send_position_setpoint(target, yaw)

            elif self.phase == "hold":
                if self._hold_target is not None:
                    self.mav.send_position_setpoint(self._hold_target, 0.0)

            elif self.phase == "landing":
                if not own["armed"]:
                    self._enter("idle")
