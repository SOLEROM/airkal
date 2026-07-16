"""Shared configuration: UDP channels, ports, rates. Env-overridable where useful."""

import os

def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)

def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc

# ── UDP bus ──────────────────────────────────────────────────────────────────
# Default is subnet broadcast on the loopback network: the whole demo runs on
# one host, and loopback broadcast needs no NIC, no IGMP and no routes.
# Multicast mode exists for multi-host setups (AIRKAL_BUS_MODE=multicast).
BUS_MODE = _env_str("AIRKAL_BUS_MODE", "broadcast")          # broadcast | multicast
BROADCAST_ADDR = _env_str("AIRKAL_BROADCAST_ADDR", "127.255.255.255")
MULTICAST_GROUP = _env_str("AIRKAL_MULTICAST_GROUP", "239.42.0.1")
MULTICAST_TTL = 1

PORT_STATE = 48000        # agent → all agents (the payload under study)
PORT_CMD = 48010          # C2 → agents
PORT_TELEMETRY = 48020    # agent → C2 (display/eval only)
PORT_STATS = 48030        # netstats → C2

CHANNEL_PORTS = {
    "state": PORT_STATE,
    "cmd": PORT_CMD,
    "telemetry": PORT_TELEMETRY,
    "stats": PORT_STATS,
}
PORT_CHANNELS = {port: name for name, port in CHANNEL_PORTS.items()}

MAX_DATAGRAM = 65507

# ── HTTP / MAVLink ───────────────────────────────────────────────────────────
C2_HTTP_PORT = _env_int("AIRKAL_C2_PORT", 8080)
MAVLINK_BASE_PORT = 14540   # PX4 onboard link, instance 0; +1 per instance

def mavlink_port(drone_id: int) -> int:
    """Drone ids are 1-based; PX4 instances are 0-based."""
    if drone_id < 1:
        raise ValueError(f"drone_id must be >= 1, got {drone_id}")
    return MAVLINK_BASE_PORT + drone_id - 1

# ── Rates & estimator defaults ───────────────────────────────────────────────
RATE_MIN_HZ = 0.1
RATE_MAX_HZ = 10.0
DEFAULT_RATE_HZ = 5.0
TELEMETRY_HZ = 5.0
STATS_HZ = 1.0
SIGMA_A = 3.0             # CV white-noise acceleration [m/s^2]

def clamp_rate(hz: float) -> float:
    """Share-rate policy: <= 0 pauses; otherwise clamp into [0.1, 10] Hz."""
    if hz <= 0.0:
        return 0.0
    return min(max(hz, RATE_MIN_HZ), RATE_MAX_HZ)
