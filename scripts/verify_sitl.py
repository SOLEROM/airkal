"""P1 verification: for each SITL instance print heartbeat, ODOMETRY rate and
whether EKF covariance values are populated.

    python scripts/verify_sitl.py --n 3 [--measure-s 3]

Exit code 0 only if every instance streams ODOMETRY at >= 40 Hz with finite
covariance diagonals.
"""

import argparse
import sys
import time

from pymavlink import mavutil
from pymavlink.dialects.v20 import common as mavlink2

BASE_PORT = 14540

def check_instance(idx: int, measure_s: float) -> bool:
    port = BASE_PORT + idx - 1
    conn = mavutil.mavlink_connection(f"udpin:0.0.0.0:{port}",
                                      source_system=255)
    try:
        hb = conn.wait_heartbeat(timeout=20)
        if hb is None:
            print(f"instance {idx}: NO HEARTBEAT on udp:{port}")
            return False
        print(f"instance {idx}: heartbeat sysid={conn.target_system}")
        for mid in (mavlink2.MAVLINK_MSG_ID_ODOMETRY,
                    mavlink2.MAVLINK_MSG_ID_LOCAL_POSITION_NED):
            conn.mav.command_long_send(
                conn.target_system, conn.target_component,
                mavlink2.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                float(mid), 1e6 / 50, 0, 0, 0, 0, 0)
        t0 = time.time()
        odo_count, cov = 0, None
        while time.time() - t0 < measure_s:
            m = conn.recv_match(type="ODOMETRY", blocking=True, timeout=1)
            if m is None:
                continue
            odo_count += 1
            cov = [m.pose_covariance[i] for i in (0, 6, 11)] + \
                  [m.velocity_covariance[i] for i in (0, 6, 11)]
        rate = odo_count / measure_s
        cov_ok = cov is not None and all(
            isinstance(x, float) and x == x and 0 <= x < 1e6 for x in cov)
        print(f"instance {idx}: ODOMETRY {rate:.1f} Hz, covariance "
              f"{'ok ' + str([round(x, 4) for x in cov]) if cov_ok else 'MISSING'}")
        return rate >= 40 and cov_ok
    finally:
        conn.close()

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--measure-s", type=float, default=3.0)
    args = ap.parse_args()
    results = [check_instance(i, args.measure_s)
               for i in range(1, args.n + 1)]
    if all(results):
        print(f"verify: all {args.n} instance(s) healthy")
        return 0
    print("verify: FAILED", file=sys.stderr)
    return 1

if __name__ == "__main__":
    sys.exit(main())
