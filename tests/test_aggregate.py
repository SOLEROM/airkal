import json

from common import config
from netstats.aggregate import TrafficAggregator

def wire(sender=1, seq=0, extra=""):
    return (f'{{"ch":"state","id":{sender},"seq":{seq},"t":1.0{extra}}}'
            .encode())

def make():
    return TrafficAggregator(config.PORT_CHANNELS)

def test_rates_over_one_second_window():
    agg = make()
    for k in range(10):
        agg.record(config.PORT_STATE, wire(seq=k), now=100.0 + k * 0.1)
    snap = agg.snapshot(now=100.95)
    per = snap["channels"]["state"]["senders"]["1"]
    assert per["msgs_1s"] == 10.0
    assert per["total_msgs"] == 10
    assert per["bytes_1s"] == 10 * len(wire()) / 1.0
    old = agg.snapshot(now=105.0)["channels"]["state"]["senders"]["1"]
    assert old["msgs_1s"] == 0.0                     # window slid past
    assert old["total_msgs"] == 10                   # totals persist

def test_seq_gap_loss_estimate():
    agg = make()
    for seq in (0, 1, 2, 5, 6, 9):                   # dropped 3,4,7,8
        agg.record(config.PORT_STATE, wire(seq=seq), now=100.0)
    per = agg.snapshot(100.5)["channels"]["state"]["senders"]["1"]
    assert per["seq_gaps"] == 4
    assert per["loss_pct"] == 40.0                   # 4 lost / (4 + 6 seen)

def test_per_sender_and_total_aggregation():
    agg = make()
    agg.record(config.PORT_STATE, wire(sender=1), 100.0)
    agg.record(config.PORT_STATE, wire(sender=2), 100.0)
    agg.record(config.PORT_TELEMETRY, wire(sender=1), 100.0)
    snap = agg.snapshot(100.5)
    assert set(snap["channels"]) == {"state", "telemetry"}
    assert set(snap["channels"]["state"]["senders"]) == {"1", "2"}
    assert snap["channels"]["state"]["total"]["total_msgs"] == 2

def test_malformed_packets_counted_but_bytes_kept():
    agg = make()
    agg.record(config.PORT_STATE, b"garbage not json", 100.0)
    agg.record(config.PORT_STATE, json.dumps({"id": "nope"}).encode(), 100.0)
    snap = agg.snapshot(100.5)
    assert snap["malformed"] == 2
    assert snap["channels"]["state"]["senders"]["-1"]["total_msgs"] == 2

def test_unknown_port_ignored():
    agg = make()
    agg.record(1234, wire(), 100.0)
    assert agg.snapshot(100.5)["channels"] == {}

def test_ema_converges_toward_window_rate():
    agg = make()
    now = 100.0
    ema = None
    for second in range(40):
        for k in range(5):                            # steady 5 msg/s
            agg.record(config.PORT_STATE,
                       wire(seq=second * 5 + k), now + k * 0.2)
        snap = agg.snapshot(now + 0.99)
        ema = snap["channels"]["state"]["senders"]["1"]["ema_msgs_s"]
        now += 1.0
    assert 4.0 < ema <= 5.5
