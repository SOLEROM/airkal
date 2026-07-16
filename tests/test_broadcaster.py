from agent.broadcaster import StateBroadcaster
from common import config, msg

class FakeSender:
    def __init__(self):
        self.sent = []
        self.tx_msgs = 0
        self.tx_bytes = 0

    def send(self, payload: bytes) -> int:
        self.sent.append(payload)
        self.tx_msgs += 1
        self.tx_bytes += len(payload)
        return len(payload)

def make(state=None, rate=2.0):
    sender = FakeSender()
    provider = lambda: state
    return StateBroadcaster(1, provider, sender, rate_hz=rate), sender

STATE = {"p": [1.0, 2.0, -30.0], "v": [0.5, 0.0, 0.0],
         "P": [0.2] * 6, "t": 100.0}

def test_tick_sends_valid_state_message_and_counts():
    bc, sender = make(STATE)
    assert bc.tick() and bc.tick()
    assert bc.seq == 2 and sender.tx_msgs == 2
    first = msg.decode(sender.sent[0])
    assert first["ch"] == "state" and first["id"] == 1 and first["seq"] == 0
    assert msg.decode(sender.sent[1])["seq"] == 1
    assert bc.tx_msgs == 2 and bc.tx_bytes == sum(len(s) for s in sender.sent)

def test_tick_skips_when_no_state():
    bc, sender = make(state=None)
    assert not bc.tick()
    assert bc.seq == 0 and sender.tx_msgs == 0 and bc.skipped_no_state == 1

def test_set_rate_clamps_and_tracks_commanded():
    bc, _ = make(STATE)
    assert bc.set_rate(50.0) == config.RATE_MAX_HZ
    assert bc.rate_cmd == 50.0
    assert bc.set_rate(0.01) == config.RATE_MIN_HZ
    assert bc.set_rate(0.0) == 0.0          # paused
    assert bc.set_rate(-5.0) == 0.0
    assert bc.set_rate(1.5) == 1.5

def test_initial_rate_is_clamped_too():
    bc, _ = make(STATE, rate=99.0)
    assert bc.rate_applied == config.RATE_MAX_HZ and bc.rate_cmd == 99.0
