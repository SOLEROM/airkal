import pytest

from c2.fanout import CmdFanout
from common import msg

class FakeSender:
    def __init__(self):
        self.sent = []

    def send(self, payload: bytes) -> int:
        self.sent.append(payload)
        return len(payload)

    def close(self):
        pass

def make():
    sender = FakeSender()
    return CmdFanout(sender=sender, now=lambda: 500.0), sender

def test_send_rate_builds_valid_cmd_with_increasing_seq():
    fanout, sender = make()
    fanout.send_rate("all", 1.0)
    fanout.send_rate(2, 0.5)
    first = msg.decode(sender.sent[0])
    second = msg.decode(sender.sent[1])
    assert first["cmd"] == "set_rate" and first["hz"] == 1.0
    assert first["target"] == "all" and second["target"] == 2
    assert (first["seq"], second["seq"]) == (0, 1)

def test_send_pattern_maps_actions_to_commands():
    fanout, sender = make()
    for action, cmd in (("start", "pattern_start"), ("stop", "pattern_stop"),
                        ("land", "land")):
        fanout.send_pattern("all", action)
        assert msg.decode(sender.sent[-1])["cmd"] == cmd

def test_invalid_inputs_raise_before_anything_is_sent():
    fanout, sender = make()
    with pytest.raises(KeyError):
        fanout.send_pattern("all", "explode")
    with pytest.raises(msg.MsgError):
        fanout.send_rate("all", -1.0)
    with pytest.raises(msg.MsgError):
        fanout.send_rate(0, 1.0)          # drone ids are 1-based
    assert sender.sent == []
