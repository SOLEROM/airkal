"""Receive side of the state channel: validates incoming packets and feeds
them into the PeerTrackerBank. Malformed traffic is counted, never fatal.
"""

import logging

from common import msg
from kalmanlib import PeerTrackerBank

log = logging.getLogger(__name__)

class PeerTracking:
    def __init__(self, own_id: int, sigma_a: float):
        self.bank = PeerTrackerBank(own_id=own_id, sigma_a=sigma_a)
        self.rx_msgs = 0
        self.rx_bytes = 0
        self.rx_malformed = 0
        self.rx_other_channel = 0

    def on_datagram(self, data: bytes, addr: tuple) -> None:
        try:
            parsed = msg.decode(data)
        except msg.MsgError:
            self.rx_malformed += 1
            return
        if parsed["ch"] != "state":
            self.rx_other_channel += 1
            return
        self.rx_msgs += 1
        self.rx_bytes += len(data)
        self.bank.on_packet(parsed)

    def estimates(self, t_query: float) -> dict:
        """Wire-format peer estimates for the telemetry message."""
        return {
            str(pid): {"p_hat": [round(x, 3) for x in est.p],
                       "sigma": round(est.sigma, 4),
                       "age": round(max(0.0, est.age), 3)}
            for pid, est in self.bank.predict_all(t_query).items()
        }

    def counters(self) -> dict:
        return {
            "rx_msgs": self.rx_msgs,
            "rx_bytes": self.rx_bytes,
            "rx_malformed": self.rx_malformed,
            **self.bank.counters(),
        }
