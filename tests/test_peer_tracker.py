import numpy as np
import pytest

from kalmanlib import models, kf
from kalmanlib.peer_tracker import PeerTracker, PeerTrackerBank

P_DIAG = [0.25, 0.25, 0.4, 0.04, 0.04, 0.09]

def pkt(peer=3, seq=0, t=100.0, p=(0.0, 0.0, -30.0), v=(2.0, 0.0, 0.0),
        P=tuple(P_DIAG)):
    return {"id": peer, "seq": seq, "t": t, "p": list(p), "v": list(v),
            "P": list(P)}

# ── PeerTracker ──────────────────────────────────────────────────────────────

def test_first_packet_initializes_from_measurement():
    trk = PeerTracker(3)
    assert not trk.initialized
    assert trk.on_packet(pkt())
    est = trk.predict(100.0)
    assert est.p == (0.0, 0.0, -30.0)
    assert est.v == (2.0, 0.0, 0.0)
    assert est.P_diag == tuple(P_DIAG)
    assert est.age == 0.0

def test_predict_before_any_packet_raises():
    with pytest.raises(RuntimeError):
        PeerTracker(3).predict(0.0)

def test_prediction_is_linear_between_packets():
    trk = PeerTracker(3)
    trk.on_packet(pkt(seq=0, t=100.0, p=(0, 0, -30), v=(2.0, -1.0, 0.0)))
    est = trk.predict(101.5)
    assert np.allclose(est.p, [3.0, -1.5, -30.0])
    assert np.allclose(est.v, [2.0, -1.0, 0.0])

def test_uncertainty_grows_with_silence():
    trk = PeerTracker(3)
    trk.on_packet(pkt())
    sigmas = [trk.predict(100.0 + dt).sigma for dt in (0.0, 0.5, 2.0, 5.0)]
    assert sigmas == sorted(sigmas)
    assert sigmas[-1] > 2 * sigmas[0]

def test_update_shrinks_uncertainty_vs_prediction():
    trk = PeerTracker(3)
    trk.on_packet(pkt(seq=0, t=100.0))
    grown = trk.predict(102.0).sigma
    trk.on_packet(pkt(seq=1, t=102.0, p=(4.0, 0.0, -30.0)))
    assert trk.predict(102.0).sigma < grown

def test_out_of_order_and_duplicates_dropped():
    trk = PeerTracker(3)
    assert trk.on_packet(pkt(seq=5, t=100.0))
    assert not trk.on_packet(pkt(seq=5, t=100.5))     # duplicate seq
    assert not trk.on_packet(pkt(seq=4, t=101.0))     # old seq
    assert not trk.on_packet(pkt(seq=6, t=100.0))     # non-advancing time
    assert trk.on_packet(pkt(seq=6, t=100.6))
    assert trk.accepted == 2 and trk.rejected == 3

def test_predict_clamps_queries_before_last_update():
    trk = PeerTracker(3)
    trk.on_packet(pkt(seq=0, t=100.0))
    est = trk.predict(99.0)                            # earlier than the packet
    assert est.p == (0.0, 0.0, -30.0)
    assert est.age < 0                                 # age is honest, state clamped

def test_zero_reported_covariance_gets_floored():
    trk = PeerTracker(3)
    trk.on_packet(pkt(P=(0, 0, 0, 0, 0, 0)))
    trk.on_packet(pkt(seq=1, t=100.5, P=(0, 0, 0, 0, 0, 0)))
    assert all(np.isfinite(trk.predict(101.0).P_diag))

def test_nees_consistency_on_simulated_cv_track():
    """Filter covariance must roughly match its actual error (NEES ≈ state dim)."""
    rng = np.random.default_rng(42)
    dt, sigma_a, r_pos, r_vel = 0.5, 1.0, 0.25, 0.04
    F, Q = models.cv_F(dt), models.cv_Q(dt, sigma_a)
    truth = np.array([0.0, 0.0, -30.0, 2.0, 1.0, 0.0])
    trk = PeerTracker(3, sigma_a=sigma_a)
    nees = []
    for k in range(400):
        t = 100.0 + k * dt
        noise = rng.multivariate_normal(np.zeros(6), Q) if k else np.zeros(6)
        truth = F @ truth + noise
        z = truth + rng.normal(0, 1, 6) * np.sqrt([r_pos] * 3 + [r_vel] * 3)
        trk.on_packet(pkt(seq=k, t=t, p=z[:3], v=z[3:],
                          P=[r_pos] * 3 + [r_vel] * 3))
        if k > 20:
            est = trk.predict(t)
            err = np.array(est.p + est.v) - truth
            P = np.diag(est.P_diag)   # diag is enough for a coarse NEES check
            nees.append(err @ np.linalg.solve(P, err))
    mean_nees = float(np.mean(nees))
    assert 3.0 < mean_nees < 10.0     # 6-dim state → expect ≈ 6

# ── PeerTrackerBank ──────────────────────────────────────────────────────────

def test_bank_ignores_own_packets_and_routes_peers():
    bank = PeerTrackerBank(own_id=1)
    assert not bank.on_packet(pkt(peer=1))
    assert bank.on_packet(pkt(peer=2))
    assert bank.on_packet(pkt(peer=3, t=100.2))
    ests = bank.predict_all(101.0)
    assert set(ests) == {2, 3}
    assert bank.counters() == {"peers": 2, "accepted": 2, "rejected": 0,
                               "ignored_own": 1}

def test_bank_predict_all_skips_uninitialized_and_orders_by_id():
    bank = PeerTrackerBank(own_id=1)
    bank.on_packet(pkt(peer=2))
    ests = bank.predict_all(100.5)
    assert list(ests) == [2]
    assert ests[2].peer_id == 2
    assert ests[2].age == pytest.approx(0.5)
