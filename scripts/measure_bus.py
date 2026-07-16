"""Passive bus measurement for the smoke test: listen on the state and
telemetry channels for a while, print one JSON summary line.

    python scripts/measure_bus.py --seconds 6
    → {"state_hz": {"1": 2.02}, "rate_applied": {"1": 2.0}, ...}
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import config, msg, udpbus

async def measure(seconds: float) -> dict:
    state_counts: dict[int, int] = {}
    rate_applied: dict[int, float] = {}
    phase: dict[int, str] = {}

    def on_state(data: bytes, addr) -> None:
        try:
            parsed = msg.decode(data)
        except msg.MsgError:
            return
        if parsed["ch"] == "state":
            state_counts[parsed["id"]] = state_counts.get(parsed["id"], 0) + 1

    def on_telemetry(data: bytes, addr) -> None:
        try:
            parsed = msg.decode(data)
        except msg.MsgError:
            return
        if parsed["ch"] == "telemetry":
            rate_applied[parsed["id"]] = parsed["rate_applied"]
            phase[parsed["id"]] = parsed.get("phase", "?")

    rx1 = await udpbus.open_rx(config.PORT_STATE, on_state)
    rx2 = await udpbus.open_rx(config.PORT_TELEMETRY, on_telemetry)
    t0 = time.time()
    await asyncio.sleep(seconds)
    elapsed = time.time() - t0
    rx1.close()
    rx2.close()
    return {
        "seconds": round(elapsed, 2),
        "state_hz": {str(k): round(v / elapsed, 2)
                     for k, v in sorted(state_counts.items())},
        "rate_applied": {str(k): v for k, v in sorted(rate_applied.items())},
        "phase": {str(k): v for k, v in sorted(phase.items())},
    }

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=6.0)
    args = ap.parse_args()
    print(json.dumps(asyncio.run(measure(args.seconds))))

if __name__ == "__main__":
    main()
