"""Wire schema: every UDP message on every channel is one compact JSON object
with a common envelope {ch, id, seq, t}. Validation runs at every receive
boundary (malformed packets are counted and dropped, never crash a tool) and
at every send (fail fast on programming errors).
"""

import json
import math
from typing import Any

from common import config

class MsgError(ValueError):
    """Raised for any malformed or schema-violating message."""

CHANNELS = ("state", "cmd", "telemetry", "stats")
COMMANDS = ("set_rate", "pattern_start", "pattern_stop", "land")

# ── low-level helpers ────────────────────────────────────────────────────────

def _require(cond: bool, why: str) -> None:
    if not cond:
        raise MsgError(why)

def _num(msg: dict, key: str, minimum: float | None = None) -> float:
    val = msg.get(key)
    _require(isinstance(val, (int, float)) and not isinstance(val, bool),
             f"field {key!r} must be a number")
    _require(math.isfinite(val), f"field {key!r} must be finite")
    if minimum is not None:
        _require(val >= minimum, f"field {key!r} must be >= {minimum}")
    return float(val)

def _int(msg: dict, key: str, minimum: int = 0) -> int:
    val = msg.get(key)
    _require(isinstance(val, int) and not isinstance(val, bool),
             f"field {key!r} must be an integer")
    _require(val >= minimum, f"field {key!r} must be >= {minimum}")
    return val

def _vec(msg: dict, key: str, n: int, minimum: float | None = None) -> list[float]:
    val = msg.get(key)
    _require(isinstance(val, list) and len(val) == n,
             f"field {key!r} must be a list of {n} numbers")
    out = []
    for i, x in enumerate(val):
        _require(isinstance(x, (int, float)) and not isinstance(x, bool)
                 and math.isfinite(x), f"field {key!r}[{i}] must be a finite number")
        if minimum is not None:
            _require(x >= minimum, f"field {key!r}[{i}] must be >= {minimum}")
        out.append(float(x))
    return out

# ── per-channel validators ───────────────────────────────────────────────────

def _validate_state(msg: dict) -> None:
    _vec(msg, "p", 3)
    _vec(msg, "v", 3)
    _vec(msg, "P", 6, minimum=0.0)

def _validate_cmd(msg: dict) -> None:
    target = msg.get("target")
    ok = target == "all" or (isinstance(target, int)
                             and not isinstance(target, bool) and target >= 1)
    _require(ok, 'field "target" must be "all" or a drone id >= 1')
    cmd = msg.get("cmd")
    _require(cmd in COMMANDS, f'field "cmd" must be one of {COMMANDS}')
    if cmd == "set_rate":
        hz = _num(msg, "hz", minimum=0.0)
        _require(hz <= 100.0, 'field "hz" is implausibly large (> 100)')

def _validate_telemetry(msg: dict) -> None:
    _validate_state(msg)
    _require(isinstance(msg.get("armed"), bool), 'field "armed" must be a bool')
    _require(isinstance(msg.get("mode"), str), 'field "mode" must be a string')
    _num(msg, "rate_cmd", minimum=0.0)
    _num(msg, "rate_applied", minimum=0.0)
    peers = msg.get("peers")
    _require(isinstance(peers, dict), 'field "peers" must be an object')
    for pid, est in peers.items():
        _require(isinstance(est, dict), f"peer {pid!r} estimate must be an object")
        _vec(est, "p_hat", 3)
        _num(est, "sigma", minimum=0.0)
        _num(est, "age", minimum=0.0)
    counters = msg.get("counters")
    _require(isinstance(counters, dict), 'field "counters" must be an object')
    for key, val in counters.items():
        _require(isinstance(val, (int, float)) and not isinstance(val, bool)
                 and math.isfinite(val), f"counter {key!r} must be a finite number")

def _validate_stats(msg: dict) -> None:
    _require(isinstance(msg.get("channels"), dict),
             'field "channels" must be an object')

_VALIDATORS = {
    "state": _validate_state,
    "cmd": _validate_cmd,
    "telemetry": _validate_telemetry,
    "stats": _validate_stats,
}

def validate(msg: Any) -> dict:
    """Validate the envelope + channel payload; return the message unchanged."""
    _require(isinstance(msg, dict), "message must be a JSON object")
    _require(msg.get("ch") in CHANNELS, f'field "ch" must be one of {CHANNELS}')
    _int(msg, "id", minimum=0)
    _int(msg, "seq", minimum=0)
    _num(msg, "t", minimum=0.0)
    _VALIDATORS[msg["ch"]](msg)
    return msg

# ── encode / decode ──────────────────────────────────────────────────────────

def encode(msg: dict) -> bytes:
    """Validate and serialize to single-line compact JSON."""
    validate(msg)
    data = json.dumps(msg, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(data) > config.MAX_DATAGRAM:
        raise MsgError(f"encoded message too large ({len(data)} bytes)")
    return data

def decode(data: bytes) -> dict:
    """Parse and validate a received datagram. Raises MsgError on any problem."""
    if len(data) > config.MAX_DATAGRAM:
        raise MsgError(f"datagram too large ({len(data)} bytes)")
    try:
        msg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MsgError(f"not valid JSON: {exc}") from exc
    return validate(msg)

# ── builders ─────────────────────────────────────────────────────────────────

def make_state(drone_id: int, seq: int, t: float,
               p: list[float], v: list[float], P: list[float]) -> dict:
    return validate({"ch": "state", "id": drone_id, "seq": seq, "t": t,
                     "p": [round(float(x), 3) for x in p],
                     "v": [round(float(x), 3) for x in v],
                     "P": [round(float(x), 4) for x in P]})

def make_cmd(target: Any, cmd: str, seq: int, t: float,
             hz: float | None = None, sender_id: int = 0) -> dict:
    msg: dict = {"ch": "cmd", "id": sender_id, "seq": seq, "t": t,
                 "target": target, "cmd": cmd}
    if hz is not None:
        msg["hz"] = float(hz)
    return validate(msg)

def make_telemetry(drone_id: int, seq: int, t: float, *,
                   p: list[float], v: list[float], P: list[float],
                   armed: bool, mode: str, phase: str,
                   rate_cmd: float, rate_applied: float,
                   time_boot_ms: int, peers: dict, counters: dict) -> dict:
    return validate({"ch": "telemetry", "id": drone_id, "seq": seq, "t": t,
                     "p": [round(float(x), 3) for x in p],
                     "v": [round(float(x), 3) for x in v],
                     "P": [round(float(x), 4) for x in P],
                     "armed": armed, "mode": mode, "phase": phase,
                     "rate_cmd": float(rate_cmd),
                     "rate_applied": float(rate_applied),
                     "time_boot_ms": int(time_boot_ms),
                     "peers": peers, "counters": counters})

def make_stats(seq: int, t: float, channels: dict, malformed: int = 0) -> dict:
    return validate({"ch": "stats", "id": 0, "seq": seq, "t": t,
                     "channels": channels, "malformed": malformed})
