"""Per-drone agent process.

    python -m agent.main --id 1 [--rate 2.0] [--param-file sitl/params.override]

Wires together: MAVLink adapter (own EKF state from PX4), state broadcaster
(runtime-controllable rate), peer tracker bank (state channel in), command
handler (cmd channel in), and the 5 Hz telemetry reporter (telemetry channel
out). The data path is peer-to-peer; C2 is only a command source/observer.
"""

import argparse
import asyncio
import logging
import os
import time

from agent.broadcaster import StateBroadcaster
from agent.flight import FlightDriver
from agent.mav import MavClient
from agent.tracker_io import PeerTracking
from common import config, msg, udpbus

log = logging.getLogger("agent")

class Agent:
    def __init__(self, drone_id: int, rate_hz: float, param_file: str | None,
                 mav_port: int | None):
        self.drone_id = drone_id
        self.mav = MavClient(drone_id, port=mav_port, param_file=param_file)
        self.tracking = PeerTracking(own_id=drone_id, sigma_a=config.SIGMA_A)
        self.state_tx = udpbus.BusSender(config.PORT_STATE)
        self.telemetry_tx = udpbus.BusSender(config.PORT_TELEMETRY)
        self.broadcaster = StateBroadcaster(drone_id, self.mav.own_state,
                                            self.state_tx, rate_hz)
        self.flight = FlightDriver(self.mav, drone_id)
        self.cmds_applied = 0
        self.cmds_malformed = 0
        self._telemetry_seq = 0

    # ── command channel ──────────────────────────────────────────────────────

    def on_cmd_datagram(self, data: bytes, addr: tuple) -> None:
        try:
            parsed = msg.decode(data)
        except msg.MsgError:
            self.cmds_malformed += 1
            return
        if parsed["ch"] != "cmd":
            return
        target = parsed["target"]
        if target != "all" and target != self.drone_id:
            return
        cmd = parsed["cmd"]
        log.info("cmd %s (target=%s)", cmd, target)
        if cmd == "set_rate":
            self.broadcaster.set_rate(parsed["hz"])
        else:
            self.flight.handle_cmd(cmd)
        self.cmds_applied += 1

    # ── telemetry channel ────────────────────────────────────────────────────

    def _telemetry_msg(self) -> dict | None:
        own = self.mav.own_state()
        if own is None:
            return None
        now = time.time()
        counters = {
            "tx_msgs": self.broadcaster.tx_msgs,
            "tx_bytes": self.broadcaster.tx_bytes,
            "cmds_applied": self.cmds_applied,
            **self.tracking.counters(),
        }
        built = msg.make_telemetry(
            self.drone_id, self._telemetry_seq, now,
            p=own["p"], v=own["v"], P=own["P"],
            armed=own["armed"], mode=own["mode"], phase=self.flight.phase,
            rate_cmd=max(0.0, self.broadcaster.rate_cmd),
            rate_applied=self.broadcaster.rate_applied,
            time_boot_ms=own["time_boot_ms"],
            peers=self.tracking.estimates(now), counters=counters)
        self._telemetry_seq += 1
        return built

    async def telemetry_loop(self) -> None:
        period = 1.0 / config.TELEMETRY_HZ
        while True:
            await asyncio.sleep(period)
            built = self._telemetry_msg()
            if built is not None:
                self.telemetry_tx.send(msg.encode(built))

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        self.mav.start()
        log.info("waiting for PX4 heartbeat on udp:%d ...", self.mav.port)
        while not self.mav.wait_connected(timeout=1.0):
            await asyncio.sleep(0)   # keep the event loop responsive
        log.info("connected to PX4 (odometry covariance: %s)",
                 "pending" if not self.mav.odometry_cov_ok else "ok")

        rx_state = await udpbus.open_rx(config.PORT_STATE,
                                        self.tracking.on_datagram)
        rx_cmd = await udpbus.open_rx(config.PORT_CMD, self.on_cmd_datagram)
        try:
            await asyncio.gather(self.broadcaster.run(),
                                 self.telemetry_loop(),
                                 self.flight.run())
        finally:
            rx_state.close()
            rx_cmd.close()
            self.state_tx.close()
            self.telemetry_tx.close()
            self.mav.close()

def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="airkal per-drone agent")
    ap.add_argument("--id", type=int, required=True, help="drone id (1-based)")
    ap.add_argument("--rate", type=float, default=config.DEFAULT_RATE_HZ,
                    help="initial share rate [Hz]")
    ap.add_argument("--mav-port", type=int, default=None,
                    help="override MAVLink udp port (default 14540+id-1)")
    ap.add_argument("--param-file", default=None,
                    help="PX4 parameter overlay applied on connect")
    args = ap.parse_args(argv)
    if args.id < 1:
        ap.error("--id must be >= 1")
    return args

def main(argv=None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=os.environ.get("AIRKAL_LOG", "INFO"),
        format=f"%(asctime)s agent-{args.id} %(levelname)s %(name)s: %(message)s")
    agent = Agent(args.id, args.rate, args.param_file, args.mav_port)
    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        log.info("stopped")

if __name__ == "__main__":
    main()
