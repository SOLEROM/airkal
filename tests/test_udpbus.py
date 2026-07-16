import asyncio
import importlib

import pytest

from common import config, msg, udpbus

TEST_PORT = 48999   # off the real channel range

def _roundtrip(n_receivers: int = 1, port: int = TEST_PORT) -> list[bytes]:
    """Send one datagram, collect what each receiver saw."""

    async def run():
        inboxes: list[list[bytes]] = [[] for _ in range(n_receivers)]
        transports = []
        for inbox in inboxes:
            transports.append(await udpbus.open_rx(
                port, lambda data, addr, inbox=inbox: inbox.append(data)))
        sender = udpbus.BusSender(port)
        try:
            sender.send(b'{"probe":1}')
            await asyncio.sleep(0.2)
        finally:
            sender.close()
            for tr in transports:
                tr.close()
        return [inbox[0] if inbox else b"" for inbox in inboxes]

    return asyncio.run(run())

def test_broadcast_loopback_roundtrip():
    assert _roundtrip() == [b'{"probe":1}']

def test_multiple_subscribers_on_same_port_all_receive():
    assert _roundtrip(n_receivers=3) == [b'{"probe":1}'] * 3

def test_sender_counters():
    async def run():
        sender = udpbus.BusSender(TEST_PORT + 1)
        try:
            sender.send(b"abc")
            sender.send(b"defgh")
        finally:
            sender.close()
        return sender.tx_msgs, sender.tx_bytes
    assert asyncio.run(run()) == (2, 8)

def test_tx_addr_modes(monkeypatch):
    monkeypatch.setattr(config, "BUS_MODE", "broadcast")
    assert udpbus.tx_addr(48000) == (config.BROADCAST_ADDR, 48000)
    monkeypatch.setattr(config, "BUS_MODE", "multicast")
    assert udpbus.tx_addr(48000) == (config.MULTICAST_GROUP, 48000)

def test_multicast_roundtrip_if_available(monkeypatch):
    monkeypatch.setattr(config, "BUS_MODE", "multicast")
    try:
        got = _roundtrip(port=TEST_PORT + 2)
    except OSError as exc:
        pytest.skip(f"multicast unavailable on this host: {exc}")
    if got != [b'{"probe":1}']:
        pytest.skip("multicast datagram not looped back on this host")

def test_bad_handler_does_not_kill_receive_loop():
    async def run():
        seen = []

        def handler(data, addr):
            seen.append(data)
            raise RuntimeError("boom")

        transport = await udpbus.open_rx(TEST_PORT + 3, handler)
        sender = udpbus.BusSender(TEST_PORT + 3)
        try:
            sender.send(b"one")
            await asyncio.sleep(0.1)
            sender.send(b"two")
            await asyncio.sleep(0.1)
        finally:
            sender.close()
            transport.close()
        return seen

    assert asyncio.run(run()) == [b"one", b"two"]

def test_config_env_override_roundtrip(monkeypatch):
    monkeypatch.setenv("AIRKAL_C2_PORT", "9999")
    monkeypatch.setenv("AIRKAL_BUS_MODE", "multicast")
    cfg = importlib.reload(config)
    try:
        assert cfg.C2_HTTP_PORT == 9999
        assert cfg.BUS_MODE == "multicast"
        monkeypatch.setenv("AIRKAL_C2_PORT", "nope")
        with pytest.raises(ValueError):
            importlib.reload(config)
    finally:
        monkeypatch.undo()
        importlib.reload(config)
