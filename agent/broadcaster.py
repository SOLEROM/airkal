"""State broadcaster: publishes this drone's fused state on the state channel
at a runtime-controllable rate. The rate variable is the knob the whole demo
is about — settable per-drone or fleet-wide from the C2 layer at any moment
(0 pauses; otherwise clamped to [0.1, 10] Hz).
"""

import asyncio
import logging
import time
from typing import Callable

from common import config, msg

log = logging.getLogger(__name__)

class StateBroadcaster:
    def __init__(self, drone_id: int,
                 state_provider: Callable[[], dict | None],
                 sender,                       # udpbus.BusSender-compatible
                 rate_hz: float = config.DEFAULT_RATE_HZ,
                 now: Callable[[], float] = time.time):
        self.drone_id = drone_id
        self._state_provider = state_provider
        self._sender = sender
        self._now = now
        self.rate_cmd = float(rate_hz)                  # last requested value
        self.rate_applied = config.clamp_rate(rate_hz)  # what actually runs
        self.seq = 0
        self.skipped_no_state = 0

    def set_rate(self, hz: float) -> float:
        """Apply a rate request; returns the clamped value in effect."""
        self.rate_cmd = float(hz)
        self.rate_applied = config.clamp_rate(hz)
        log.info("drone %d: share rate -> %.2f Hz (requested %.2f)",
                 self.drone_id, self.rate_applied, self.rate_cmd)
        return self.rate_applied

    @property
    def tx_msgs(self) -> int:
        return self._sender.tx_msgs

    @property
    def tx_bytes(self) -> int:
        return self._sender.tx_bytes

    def tick(self) -> bool:
        """Broadcast one state message; False if no fresh state to send."""
        state = self._state_provider()
        if state is None:
            self.skipped_no_state += 1
            return False
        wire = msg.encode(msg.make_state(self.drone_id, self.seq, state["t"],
                                         state["p"], state["v"], state["P"]))
        self._sender.send(wire)
        self.seq += 1
        return True

    async def run(self) -> None:
        """Deadline-based loop so the observed rate tracks rate_applied even
        when it changes mid-flight; a paused broadcaster polls for un-pause."""
        next_deadline = self._now()
        while True:
            rate = self.rate_applied
            if rate <= 0.0:
                await asyncio.sleep(0.2)
                next_deadline = self._now()
                continue
            self.tick()
            period = 1.0 / rate
            now = self._now()
            next_deadline = max(next_deadline + period, now - period)
            await asyncio.sleep(max(0.0, next_deadline - now))
