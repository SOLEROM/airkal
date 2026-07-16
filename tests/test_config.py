import pytest

from common import config

def test_clamp_rate_pauses_at_zero_and_below():
    assert config.clamp_rate(0.0) == 0.0
    assert config.clamp_rate(-3.0) == 0.0

def test_default_rate_is_5hz_within_clamp_bounds():
    assert config.DEFAULT_RATE_HZ == 5.0
    assert config.clamp_rate(config.DEFAULT_RATE_HZ) == config.DEFAULT_RATE_HZ

def test_clamp_rate_bounds():
    assert config.clamp_rate(0.01) == config.RATE_MIN_HZ
    assert config.clamp_rate(99.0) == config.RATE_MAX_HZ
    assert config.clamp_rate(2.5) == 2.5

def test_channel_port_maps_are_inverse():
    for name, port in config.CHANNEL_PORTS.items():
        assert config.PORT_CHANNELS[port] == name
    assert len(config.PORT_CHANNELS) == len(config.CHANNEL_PORTS) == 4

def test_mavlink_port_is_one_based():
    assert config.mavlink_port(1) == 14540
    assert config.mavlink_port(3) == 14542
    with pytest.raises(ValueError):
        config.mavlink_port(0)
