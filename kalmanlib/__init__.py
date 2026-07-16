"""Small, generic linear Kalman filtering library (numpy-only).

- kf: pure predict/update functions (Joseph-form update).
- models: constant-velocity process model in n spatial dimensions.
- peer_tracker: per-peer tracker bank driven by received state packets.
"""

from kalmanlib.peer_tracker import PeerEstimate, PeerTracker, PeerTrackerBank

__all__ = ["PeerEstimate", "PeerTracker", "PeerTrackerBank"]
