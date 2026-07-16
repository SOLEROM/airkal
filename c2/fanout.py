"""Command fan-out: every accepted API request becomes one validated cmd
message on the cmd channel. C2 never touches the data path."""

import time
from typing import Callable

from common import config, msg, udpbus

class CmdFanout:
    def __init__(self, sender=None, now: Callable[[], float] = time.time):
        self._sender = sender if sender is not None \
            else udpbus.BusSender(config.PORT_CMD)
        self._now = now
        self._seq = 0

    def _send(self, built: dict) -> dict:
        self._sender.send(msg.encode(built))
        self._seq += 1
        return built

    def send_rate(self, target, hz: float) -> dict:
        return self._send(msg.make_cmd(target, "set_rate", self._seq,
                                       self._now(), hz=hz))

    def send_pattern(self, target, action: str) -> dict:
        cmd = {"start": "pattern_start", "stop": "pattern_stop",
               "land": "land"}[action]
        return self._send(msg.make_cmd(target, cmd, self._seq, self._now()))

    def close(self) -> None:
        self._sender.close()
