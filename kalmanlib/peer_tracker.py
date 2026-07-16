"""Per-peer constant-velocity trackers driven by received state packets.

Each PeerTracker holds the filter state for one peer:
- on_packet(msg): initialize from the first packet, then predict-to-packet-time
  and update using the sender's reported covariance diagonal as R. Out-of-order
  or duplicate packets (by seq, then by t) are dropped.
- predict(t_query): predict-only estimate at an arbitrary time without touching
  the stored state — this is what makes the estimate continuous between
  packets, with covariance growing during silence.

PeerTrackerBank routes packets by sender id and ignores the owner's own id.
Packet dicts use the wire-schema keys (already validated upstream):
  {"id", "seq", "t", "p": [3], "v": [3], "P": [6 diag: pos+vel]}.
"""

from dataclasses import dataclass

import numpy as np

from kalmanlib import kf, models

_VAR_FLOOR = 1e-4   # keeps a reported all-zero covariance from going singular
_DIMS = 3

@dataclass(frozen=True)
class PeerEstimate:
    peer_id: int
    p: tuple[float, float, float]      # predicted NED position [m]
    v: tuple[float, float, float]      # predicted NED velocity [m/s]
    P_diag: tuple[float, ...]          # predicted covariance diagonal (6)
    sigma: float                       # RMS 1-sigma position uncertainty [m]
    age: float                         # t_query - time of last accepted packet [s]
    t: float                           # query time

class PeerTracker:
    def __init__(self, peer_id: int, sigma_a: float = 3.0):
        self.peer_id = peer_id
        self.sigma_a = sigma_a
        self._x: np.ndarray | None = None
        self._P: np.ndarray | None = None
        self._t = 0.0
        self._last_seq = -1
        self.accepted = 0
        self.rejected = 0

    @property
    def initialized(self) -> bool:
        return self._x is not None

    @property
    def last_update_t(self) -> float:
        return self._t

    def on_packet(self, pkt: dict) -> bool:
        """Fold one received state packet in; False if dropped (stale/dup)."""
        seq, t = int(pkt["seq"]), float(pkt["t"])
        if self.initialized and (seq <= self._last_seq or t <= self._t):
            self.rejected += 1
            return False

        z = np.array(list(pkt["p"]) + list(pkt["v"]), dtype=float)
        R_diag = np.maximum(np.array(pkt["P"], dtype=float), _VAR_FLOOR)

        if not self.initialized:
            self._x = z
            self._P = np.diag(R_diag)
        else:
            dt = t - self._t
            x, P = kf.predict(self._x, self._P,
                              models.cv_F(dt, _DIMS),
                              models.cv_Q(dt, self.sigma_a, _DIMS))
            self._x, self._P = kf.update(x, P, z, models.cv_H(_DIMS),
                                         np.diag(R_diag))
        self._t = t
        self._last_seq = seq
        self.accepted += 1
        return True

    def predict(self, t_query: float) -> PeerEstimate:
        """Predict-only estimate at t_query; stored state is not advanced."""
        if not self.initialized:
            raise RuntimeError(f"peer {self.peer_id}: no packet received yet")
        dt = max(0.0, t_query - self._t)
        x, P = kf.predict(self._x, self._P,
                          models.cv_F(dt, _DIMS),
                          models.cv_Q(dt, self.sigma_a, _DIMS))
        diag = np.diag(P)
        return PeerEstimate(
            peer_id=self.peer_id,
            p=tuple(float(val) for val in x[:3]),
            v=tuple(float(val) for val in x[3:]),
            P_diag=tuple(float(val) for val in diag),
            sigma=float(np.sqrt(np.mean(diag[:3]))),
            age=t_query - self._t,
            t=t_query,
        )

class PeerTrackerBank:
    """One tracker per peer; packets from own_id are ignored."""

    def __init__(self, own_id: int, sigma_a: float = 3.0):
        self.own_id = own_id
        self.sigma_a = sigma_a
        self._trackers: dict[int, PeerTracker] = {}
        self.ignored_own = 0

    def on_packet(self, pkt: dict) -> bool:
        sender = int(pkt["id"])
        if sender == self.own_id:
            self.ignored_own += 1
            return False
        tracker = self._trackers.get(sender)
        if tracker is None:
            tracker = PeerTracker(sender, self.sigma_a)
            self._trackers[sender] = tracker
        return tracker.on_packet(pkt)

    def predict_all(self, t_query: float) -> dict[int, PeerEstimate]:
        return {pid: trk.predict(t_query)
                for pid, trk in self._trackers.items() if trk.initialized}

    def counters(self) -> dict[str, int]:
        return {
            "peers": len(self._trackers),
            "accepted": sum(t.accepted for t in self._trackers.values()),
            "rejected": sum(t.rejected for t in self._trackers.values()),
            "ignored_own": self.ignored_own,
        }
