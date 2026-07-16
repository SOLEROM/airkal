"""Traffic aggregation for the UDP control plane.

Answers "how much data are we actually passing over UDP between the tools?":
per channel × sender — msgs/s and bytes/s over a 1 s window, a 10 s EMA,
mean message size, cumulative totals, and (per sender) a loss estimate from
gaps in the envelope seq counter. Time is injected everywhere for testability.
"""

from collections import deque
from dataclasses import dataclass, field

import json

WINDOW_S = 1.0
EMA_TAU_S = 10.0

@dataclass
class SenderStats:
    recent: deque = field(default_factory=deque)   # (t_arrival, nbytes)
    total_msgs: int = 0
    total_bytes: int = 0
    last_seq: int | None = None
    seq_gaps: int = 0
    ema_bytes_s: float = 0.0
    ema_msgs_s: float = 0.0
    last_ema_t: float | None = None

    def record(self, now: float, nbytes: int, seq: int | None) -> None:
        self.recent.append((now, nbytes))
        self.total_msgs += 1
        self.total_bytes += nbytes
        if seq is not None:
            if self.last_seq is not None and seq > self.last_seq + 1:
                self.seq_gaps += seq - self.last_seq - 1
            if self.last_seq is None or seq > self.last_seq:
                self.last_seq = seq

    def _prune(self, now: float) -> None:
        while self.recent and self.recent[0][0] < now - WINDOW_S:
            self.recent.popleft()

    def snapshot(self, now: float) -> dict:
        self._prune(now)
        msgs_1s = len(self.recent) / WINDOW_S
        bytes_1s = sum(nb for _, nb in self.recent) / WINDOW_S
        if self.last_ema_t is None:
            self.ema_msgs_s, self.ema_bytes_s = msgs_1s, bytes_1s
        else:
            dt = max(1e-3, now - self.last_ema_t)
            alpha = min(1.0, dt / EMA_TAU_S)
            self.ema_msgs_s += alpha * (msgs_1s - self.ema_msgs_s)
            self.ema_bytes_s += alpha * (bytes_1s - self.ema_bytes_s)
        self.last_ema_t = now
        received = self.total_msgs
        loss_pct = (100.0 * self.seq_gaps / (self.seq_gaps + received)
                    if self.seq_gaps else 0.0)
        return {
            "msgs_1s": round(msgs_1s, 2),
            "bytes_1s": round(bytes_1s, 1),
            "ema_msgs_s": round(self.ema_msgs_s, 2),
            "ema_bytes_s": round(self.ema_bytes_s, 1),
            "mean_size": round(self.total_bytes / received, 1) if received else 0,
            "total_msgs": self.total_msgs,
            "total_bytes": self.total_bytes,
            "seq_gaps": self.seq_gaps,
            "loss_pct": round(loss_pct, 2),
        }

class TrafficAggregator:
    """record() every datagram; snapshot() at any cadence."""

    def __init__(self, port_channels: dict[int, str]):
        self._port_channels = dict(port_channels)
        self._senders: dict[tuple[str, int], SenderStats] = {}
        self.malformed = 0

    def record(self, port: int, data: bytes, now: float) -> None:
        channel = self._port_channels.get(port)
        if channel is None:
            return
        sender_id, seq = self._parse_envelope(data)
        if sender_id is None:
            self.malformed += 1
            sender_id = -1     # still count the bytes: it IS traffic
        key = (channel, sender_id)
        if key not in self._senders:
            self._senders[key] = SenderStats()
        # only the state channel's seq is a per-sender monotonic counter we
        # want loss from; other channels report seq too, so track uniformly
        self._senders[key].record(now, len(data), seq)

    @staticmethod
    def _parse_envelope(data: bytes) -> tuple[int | None, int | None]:
        try:
            parsed = json.loads(data.decode("utf-8"))
            sender = parsed.get("id")
            seq = parsed.get("seq")
            if not isinstance(sender, int) or isinstance(sender, bool):
                return None, None
            if not isinstance(seq, int) or isinstance(seq, bool):
                seq = None
            return sender, seq
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            return None, None

    def snapshot(self, now: float) -> dict:
        channels: dict[str, dict] = {}
        for (channel, sender_id), stats in sorted(self._senders.items(),
                                                  key=lambda kv: kv[0]):
            per = stats.snapshot(now)
            chan = channels.setdefault(channel, {"senders": {}, "total": {
                "msgs_1s": 0.0, "bytes_1s": 0.0, "total_msgs": 0,
                "total_bytes": 0, "seq_gaps": 0}})
            chan["senders"][str(sender_id)] = per
            tot = chan["total"]
            tot["msgs_1s"] = round(tot["msgs_1s"] + per["msgs_1s"], 2)
            tot["bytes_1s"] = round(tot["bytes_1s"] + per["bytes_1s"], 1)
            tot["total_msgs"] += per["total_msgs"]
            tot["total_bytes"] += per["total_bytes"]
            tot["seq_gaps"] += per["seq_gaps"]
        return {"channels": channels, "malformed": self.malformed}
