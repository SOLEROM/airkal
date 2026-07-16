import pytest

from c2.errors import ErrorTracker

def tel(drone_id, t, p, peers=None):
    return {"ch": "telemetry", "id": drone_id, "seq": 0, "t": t,
            "p": list(p), "v": [0, 0, 0], "P": [0.1] * 6,
            "peers": peers or {}}

def est(p_hat, sigma=0.5, age=0.4):
    return {"p_hat": list(p_hat), "sigma": sigma, "age": age}

def test_pair_error_is_distance_between_estimate_and_truth():
    trk = ErrorTracker()
    trk.on_telemetry(tel(2, 100.0, [10.0, 0.0, -30.0]))          # truth of 2
    trk.on_telemetry(tel(1, 100.05, [0, 0, -30],
                         peers={"2": est([13.0, 4.0, -30.0])}))  # 1's view of 2
    snap = trk.snapshot()
    assert snap["1->2"]["err"] == pytest.approx(5.0, abs=1e-6)
    assert snap["1->2"]["sigma"] == 0.5

def test_nearest_in_time_alignment_picks_closest_sample():
    trk = ErrorTracker()
    trk.on_telemetry(tel(2, 100.0, [0.0, 0.0, 0.0]))
    trk.on_telemetry(tel(2, 101.0, [10.0, 0.0, 0.0]))
    trk.on_telemetry(tel(1, 100.9, [0, 0, 0], peers={"2": est([10.0, 0, 0])}))
    assert trk.snapshot()["1->2"]["err"] == pytest.approx(0.0)

def test_no_truth_within_tolerance_means_no_pair():
    trk = ErrorTracker()
    trk.on_telemetry(tel(2, 100.0, [0.0, 0.0, 0.0]))
    trk.on_telemetry(tel(1, 105.0, [0, 0, 0], peers={"2": est([1.0, 0, 0])}))
    assert trk.snapshot() == {}

def test_rolling_max_tracks_worst_error_in_window():
    trk = ErrorTracker()
    for k, err_x in enumerate((1.0, 6.0, 2.0)):
        t = 100.0 + k
        trk.on_telemetry(tel(2, t, [0.0, 0.0, 0.0]))
        trk.on_telemetry(tel(1, t, [0, 0, 0],
                             peers={"2": est([err_x, 0.0, 0.0])}))
    snap = trk.snapshot()
    assert snap["1->2"]["err"] == pytest.approx(2.0)
    assert snap["1->2"]["max"] == pytest.approx(6.0)

def test_pairs_are_directional():
    trk = ErrorTracker()
    trk.on_telemetry(tel(1, 100.0, [0.0, 0.0, 0.0]))
    trk.on_telemetry(tel(2, 100.0, [5.0, 0.0, 0.0],
                         peers={"1": est([0.5, 0.0, 0.0])}))
    trk.on_telemetry(tel(1, 100.1, [0, 0, 0],
                         peers={"2": est([5.0, 1.0, 0.0])}))
    snap = trk.snapshot()
    assert set(snap) == {"1->2", "2->1"}
    assert snap["2->1"]["err"] == pytest.approx(0.5)
    assert snap["1->2"]["err"] == pytest.approx(1.0)
