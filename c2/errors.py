"""Prediction-error computation — the demo's proof.

For every observer/peer pair (k, i): error = |drone k's telemetry-reported
prediction of peer i − drone i's own telemetry-reported position|, aligned
nearest-in-time on drone i's recent state history. Tracks the current value
and a rolling max per pair.
"""

import math
from bisect import bisect_left
from collections import deque

HISTORY_S = 30.0        # own-state history kept per drone for alignment
ALIGN_TOL_S = 1.0       # max time distance for a valid pairing
MAX_ERR_WINDOW_S = 60.0

class ErrorTracker:
    def __init__(self):
        self._truth: dict[int, deque] = {}       # id -> deque[(t, p)]
        self._pairs: dict[tuple[int, int], dict] = {}

    def on_telemetry(self, tel: dict) -> None:
        drone_id, t = tel["id"], tel["t"]
        hist = self._truth.setdefault(drone_id, deque())
        if not hist or t > hist[-1][0]:
            hist.append((t, tuple(tel["p"])))
        while hist and hist[0][0] < t - HISTORY_S:
            hist.popleft()
        for pid_str, est in tel.get("peers", {}).items():
            self._update_pair(drone_id, int(pid_str), t, est)

    def _update_pair(self, observer: int, peer: int, t: float,
                     est: dict) -> None:
        truth = self._nearest_truth(peer, t)
        if truth is None:
            return
        p_hat = est["p_hat"]
        err = math.dist(p_hat, truth)
        pair = self._pairs.setdefault((observer, peer), {"max_window": deque()})
        pair.update(t=t, err=err, sigma=est["sigma"], age=est["age"])
        window = pair["max_window"]
        window.append((t, err))
        while window and window[0][0] < t - MAX_ERR_WINDOW_S:
            window.popleft()

    def _nearest_truth(self, drone_id: int, t: float):
        hist = self._truth.get(drone_id)
        if not hist:
            return None
        times = [entry[0] for entry in hist]
        idx = bisect_left(times, t)
        best = None
        for j in (idx - 1, idx):
            if 0 <= j < len(hist):
                dt = abs(hist[j][0] - t)
                if dt <= ALIGN_TOL_S and (best is None or dt < best[0]):
                    best = (dt, hist[j][1])
        return best[1] if best else None

    def snapshot(self) -> dict:
        """{"1->2": {"err":…, "max":…, "sigma":…, "age":…, "t":…}, …}"""
        out = {}
        for (observer, peer), pair in sorted(self._pairs.items()):
            window = pair["max_window"]
            out[f"{observer}->{peer}"] = {
                "err": round(pair["err"], 3),
                "max": round(max(e for _, e in window), 3) if window else 0.0,
                "sigma": round(pair["sigma"], 3),
                "age": round(pair["age"], 3),
                "t": pair["t"],
            }
        return out
