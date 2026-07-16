"""MAVLink adapter: one PX4 SITL instance ↔ this agent.

Runs a background thread that connects to udp:14540+i, requests the EKF2
output streams, applies the parameter overlay, and keeps the latest fused
own-state (p, v, P, t). Exposes thread-safe command helpers used by the
flight driver.

EKF extraction (plan §5.1):
- primary: ODOMETRY (msg 331) at 50 Hz — pose + velocity covariance diagonals;
- p/v come from LOCAL_POSITION_NED (plain NED, no frame gymnastics);
- fallback: if ODOMETRY covariance is absent/invalid, a conservative fixed
  covariance diagonal is used so the demo keeps working.
"""

import logging
import struct
import threading
import time

from pymavlink import mavutil
from pymavlink.dialects.v20 import common as mavlink2

from common import config

log = logging.getLogger(__name__)

STATE_STALE_S = 2.0
DEFAULT_P_DIAG = (1.0, 1.0, 1.0, 0.25, 0.25, 0.25)   # conservative fallback

_PX4_MAIN_MODES = {1: "MANUAL", 2: "ALTCTL", 3: "POSCTL", 4: "AUTO",
                   5: "ACRO", 6: "OFFBOARD", 7: "STABILIZED", 8: "RATTITUDE"}
_PX4_AUTO_SUB = {1: "READY", 2: "TAKEOFF", 3: "LOITER", 4: "MISSION",
                 5: "RTL", 6: "LAND", 7: "RTGS", 8: "FOLLOW"}

# SET_POSITION_TARGET_LOCAL_NED type_mask: use position + yaw, ignore the rest.
_POS_YAW_TYPE_MASK = 0x09F8

def mode_name(custom_mode: int) -> str:
    main = (custom_mode >> 16) & 0xFF
    sub = (custom_mode >> 24) & 0xFF
    name = _PX4_MAIN_MODES.get(main, f"MODE_{main}")
    if name == "AUTO" and sub in _PX4_AUTO_SUB:
        return f"AUTO.{_PX4_AUTO_SUB[sub]}"
    return name

def parse_param_file(path: str) -> list[tuple[str, float | int]]:
    """Parse 'NAME VALUE  # comment' lines; int-looking values stay ints."""
    out: list[tuple[str, float | int]] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"{path}:{lineno}: expected 'NAME VALUE'")
            name, val = parts
            try:
                value: float | int = int(val)
            except ValueError:
                value = float(val)
            out.append((name, value))
    return out

class MavClient:
    def __init__(self, drone_id: int, port: int | None = None,
                 param_file: str | None = None):
        self.drone_id = drone_id
        self.port = port if port is not None else config.mavlink_port(drone_id)
        self.param_file = param_file
        self._master: mavutil.mavfile | None = None
        self._tx_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._own: dict | None = None
        self._P_diag = list(DEFAULT_P_DIAG)
        self._odometry_cov_ok = False
        self._armed = False
        self._custom_mode = 0
        self._connected = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=f"mav-{drone_id}")
        self._last_heartbeat_tx = 0.0

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3.0)
        if self._master is not None:
            self._master.close()

    def wait_connected(self, timeout: float) -> bool:
        return self._connected.wait(timeout)

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    # ── background thread ────────────────────────────────────────────────────

    def _run(self) -> None:
        url = f"udpin:0.0.0.0:{self.port}"
        log.info("drone %d: connecting %s", self.drone_id, url)
        self._master = mavutil.mavlink_connection(url, source_system=255,
                                                  source_component=191)
        while not self._stop.is_set():
            if self._master.wait_heartbeat(timeout=2.0) is not None:
                break
        if self._stop.is_set():
            return
        log.info("drone %d: heartbeat from sys %d", self.drone_id,
                 self._master.target_system)
        self._setup_streams()
        if self.param_file:
            self.apply_params(parse_param_file(self.param_file))
        self._connected.set()
        self._rx_loop()

    def _setup_streams(self) -> None:
        for msg_id in (mavlink2.MAVLINK_MSG_ID_LOCAL_POSITION_NED,
                       mavlink2.MAVLINK_MSG_ID_ODOMETRY):
            self.set_message_interval(msg_id, 50.0)

    def _rx_loop(self) -> None:
        while not self._stop.is_set():
            now = time.time()
            if now - self._last_heartbeat_tx >= 1.0:
                self._send_heartbeat(now)
            msg = self._master.recv_match(blocking=True, timeout=0.5)
            if msg is None:
                continue
            kind = msg.get_type()
            if kind == "LOCAL_POSITION_NED":
                self._on_local_position(msg)
            elif kind == "ODOMETRY":
                self._on_odometry(msg)
            elif kind == "HEARTBEAT":
                self._on_heartbeat(msg)
            elif kind == "COMMAND_ACK":
                if msg.result != mavlink2.MAV_RESULT_ACCEPTED:
                    log.warning("drone %d: command %d rejected (result=%d)",
                                self.drone_id, msg.command, msg.result)

    def _on_local_position(self, msg) -> None:
        with self._state_lock:
            self._own = {
                "p": [msg.x, msg.y, msg.z],
                "v": [msg.vx, msg.vy, msg.vz],
                "P": list(self._P_diag),
                "t": time.time(),
                "time_boot_ms": msg.time_boot_ms,
                "armed": self._armed,
                "mode": mode_name(self._custom_mode),
            }

    def _on_odometry(self, msg) -> None:
        try:
            diag = [msg.pose_covariance[0], msg.pose_covariance[6],
                    msg.pose_covariance[11], msg.velocity_covariance[0],
                    msg.velocity_covariance[6], msg.velocity_covariance[11]]
        except (TypeError, IndexError):
            return
        if all(isinstance(x, float) and x == x and 0.0 <= x < 1e6 for x in diag):
            with self._state_lock:
                self._P_diag = diag
                self._odometry_cov_ok = True

    def _on_heartbeat(self, msg) -> None:
        if msg.get_srcSystem() != self._master.target_system:
            return
        with self._state_lock:
            self._armed = bool(msg.base_mode
                               & mavlink2.MAV_MODE_FLAG_SAFETY_ARMED)
            self._custom_mode = msg.custom_mode

    def _send_heartbeat(self, now: float) -> None:
        with self._tx_lock:
            self._master.mav.heartbeat_send(
                mavlink2.MAV_TYPE_ONBOARD_CONTROLLER,
                mavlink2.MAV_AUTOPILOT_INVALID, 0, 0, 0)
        self._last_heartbeat_tx = now

    # ── state access ─────────────────────────────────────────────────────────

    def own_state(self) -> dict | None:
        """Latest fused own state, or None if never seen / stale."""
        with self._state_lock:
            own = self._own
            if own is None or time.time() - own["t"] > STATE_STALE_S:
                return None
            return dict(own, p=list(own["p"]), v=list(own["v"]),
                        P=list(own["P"]))

    @property
    def odometry_cov_ok(self) -> bool:
        return self._odometry_cov_ok

    # ── commands (thread-safe) ───────────────────────────────────────────────

    def _command_long(self, command: int, *params: float) -> None:
        padded = list(params) + [0.0] * (7 - len(params))
        with self._tx_lock:
            self._master.mav.command_long_send(
                self._master.target_system, self._master.target_component,
                command, 0, *padded)

    def set_message_interval(self, msg_id: int, hz: float) -> None:
        self._command_long(mavlink2.MAV_CMD_SET_MESSAGE_INTERVAL,
                           float(msg_id), 1e6 / hz)

    def apply_params(self, params: list[tuple[str, float | int]]) -> None:
        """PX4 uses byte-wise casting for INT32 params inside the float field."""
        for name, value in params:
            if isinstance(value, int):
                encoded = struct.unpack("<f", struct.pack("<i", value))[0]
                ptype = mavlink2.MAV_PARAM_TYPE_INT32
            else:
                encoded, ptype = value, mavlink2.MAV_PARAM_TYPE_REAL32
            with self._tx_lock:
                self._master.mav.param_set_send(
                    self._master.target_system, self._master.target_component,
                    name.encode("ascii"), encoded, ptype)
            log.info("drone %d: param %s = %s", self.drone_id, name, value)
            time.sleep(0.05)   # give PX4 room; no ack-tracking needed for demo

    def arm(self) -> None:
        self._command_long(mavlink2.MAV_CMD_COMPONENT_ARM_DISARM, 1.0)

    def set_mode_offboard(self) -> None:
        self._command_long(mavlink2.MAV_CMD_DO_SET_MODE,
                           float(mavlink2.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED),
                           6.0)                      # PX4 main mode OFFBOARD

    def set_mode_auto_land(self) -> None:
        self._command_long(mavlink2.MAV_CMD_DO_SET_MODE,
                           float(mavlink2.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED),
                           4.0, 6.0)                 # PX4 AUTO.LAND

    def send_position_setpoint(self, p: list[float], yaw: float) -> None:
        own = self.own_state()
        boot_ms = own["time_boot_ms"] if own else 0
        with self._tx_lock:
            self._master.mav.set_position_target_local_ned_send(
                boot_ms, self._master.target_system,
                self._master.target_component,
                mavlink2.MAV_FRAME_LOCAL_NED, _POS_YAW_TYPE_MASK,
                p[0], p[1], p[2], 0, 0, 0, 0, 0, 0, yaw, 0)
