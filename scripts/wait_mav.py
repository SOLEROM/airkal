"""Wait for a MAVLink heartbeat on a local udp port; exit 0 when seen.

    python scripts/wait_mav.py --port 14540 --timeout 60

If the port is already bound (an agent is running there), that counts as
healthy too.
"""

import argparse
import sys

from pymavlink import mavutil

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    try:
        conn = mavutil.mavlink_connection(f"udpin:0.0.0.0:{args.port}",
                                          source_system=255)
    except OSError:
        print(f"udp:{args.port} already bound — assuming an agent owns it")
        return 0
    try:
        hb = conn.wait_heartbeat(timeout=args.timeout)
        if hb is None:
            print(f"udp:{args.port}: no heartbeat within {args.timeout}s",
                  file=sys.stderr)
            return 1
        print(f"udp:{args.port}: heartbeat from sysid {conn.target_system}")
        return 0
    finally:
        conn.close()

if __name__ == "__main__":
    sys.exit(main())
