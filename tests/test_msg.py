import json
import math

import pytest

from common import msg

def _state(**over):
    base = {"ch": "state", "id": 3, "seq": 41, "t": 1000.5,
            "p": [1.0, -2.0, -30.0], "v": [0.5, 0.0, 0.0],
            "P": [0.2, 0.2, 0.4, 0.05, 0.05, 0.1]}
    base.update(over)
    return base

# ── round trips ──────────────────────────────────────────────────────────────

def test_state_round_trip():
    data = msg.encode(_state())
    assert b"\n" not in data                       # single-line JSON
    assert msg.decode(data) == _state()

def test_make_state_builder_rounds_floats():
    built = msg.make_state(1, 0, 12.3456789,
                           p=[1.23456, 0, 0], v=[0, 0, 0], P=[0.123456] * 6)
    assert built["p"][0] == 1.235
    assert built["P"][0] == 0.1235
    msg.decode(msg.encode(built))

def test_make_cmd_round_trip():
    built = msg.make_cmd("all", "set_rate", seq=2, t=5.0, hz=1.5)
    again = msg.decode(msg.encode(built))
    assert again["target"] == "all" and again["hz"] == 1.5
    per_drone = msg.make_cmd(2, "land", seq=3, t=6.0)
    assert msg.decode(msg.encode(per_drone))["target"] == 2

def test_make_telemetry_round_trip():
    built = msg.make_telemetry(
        2, 7, 100.0, p=[0, 0, -30], v=[1, 0, 0], P=[0.1] * 6,
        armed=True, mode="OFFBOARD", phase="orbit",
        rate_cmd=1.0, rate_applied=1.0, time_boot_ms=1234,
        peers={"3": {"p_hat": [5, 5, -30], "sigma": 0.4, "age": 0.2}},
        counters={"tx_msgs": 10, "tx_bytes": 1800, "rx_msgs": 20})
    assert msg.decode(msg.encode(built))["peers"]["3"]["sigma"] == 0.4

def test_make_stats_round_trip():
    built = msg.make_stats(1, 50.0, channels={"state": {"bytes_1s": 360.0}})
    assert msg.decode(msg.encode(built))["channels"]["state"]["bytes_1s"] == 360.0

# ── malformed input rejection ────────────────────────────────────────────────

@pytest.mark.parametrize("data", [
    b"", b"not json", b"[1,2,3]", b'"just a string"', b"\xff\xfe\x00",
])
def test_decode_rejects_non_object_payloads(data):
    with pytest.raises(msg.MsgError):
        msg.decode(data)

def test_decode_rejects_oversized_datagram():
    with pytest.raises(msg.MsgError):
        msg.decode(b" " * 70000)

@pytest.mark.parametrize("bad", [
    {"ch": "nope"}, {"ch": "state"},                       # bad/short envelope
    _state(id="x"), _state(id=True), _state(seq=-1),
    _state(t=float("nan")), _state(p=[1, 2]), _state(p=[1, 2, "x"]),
    _state(P=[-1, 0, 0, 0, 0, 0]),                         # negative variance
    _state(v=[1, 2, float("inf")]),
])
def test_validate_rejects_bad_state(bad):
    with pytest.raises(msg.MsgError):
        msg.validate(bad)

def test_decode_rejects_nan_smuggled_via_json():
    raw = json.dumps(_state(t=float("nan"))).encode()     # json allows NaN
    with pytest.raises(msg.MsgError):
        msg.decode(raw)

@pytest.mark.parametrize("bad", [
    {"target": 0, "cmd": "land"},          # ids are >= 1
    {"target": True, "cmd": "land"},
    {"target": "all", "cmd": "explode"},
    {"target": "all", "cmd": "set_rate"},                  # missing hz
    {"target": "all", "cmd": "set_rate", "hz": -1},
    {"target": "all", "cmd": "set_rate", "hz": 1000},
])
def test_validate_rejects_bad_cmd(bad):
    with pytest.raises(msg.MsgError):
        msg.validate({"ch": "cmd", "id": 0, "seq": 0, "t": 1.0, **bad})

def test_encode_rejects_nonfinite_before_wire():
    with pytest.raises(msg.MsgError):
        msg.encode(_state(t=float("inf")))

def test_telemetry_rejects_bad_peers_and_counters():
    good = msg.make_telemetry(
        2, 7, 100.0, p=[0, 0, 0], v=[0, 0, 0], P=[0.1] * 6,
        armed=False, mode="POSCTL", phase="idle",
        rate_cmd=2.0, rate_applied=2.0, time_boot_ms=0,
        peers={}, counters={})
    bad_peer = dict(good, peers={"3": {"p_hat": [1, 2], "sigma": 0.1, "age": 0}})
    with pytest.raises(msg.MsgError):
        msg.validate(bad_peer)
    bad_counter = dict(good, counters={"tx": float("nan")})
    with pytest.raises(msg.MsgError):
        msg.validate(bad_counter)

def test_state_wire_size_is_small():
    built = msg.make_state(3, 417, 1789475123.412,
                           p=[12.31, -40.22, -30.05], v=[3.1, 0.42, 0.0],
                           P=[0.25, 0.25, 0.4, 0.04, 0.04, 0.09])
    assert len(msg.encode(built)) < 250   # plan budget: ~180 B typical
