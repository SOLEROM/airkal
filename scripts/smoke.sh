#!/bin/bash
# End-to-end smoke test on one drone (plan §10):
#   SITL up → EKF verified → agent broadcasts at the default rate ±10%
#   → set_rate 1.0 over the cmd channel is applied → clean teardown.
# Assumes a clean host (runs 'down' first and last).
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
require_venv
require_image

cleanup() { scripts/down.sh >/dev/null 2>&1 || true; }
trap cleanup EXIT

info "0/5 clean slate"
scripts/down.sh >/dev/null

info "1/5 SITL up (1 instance)"
scripts/up.sh 1

info "2/5 verify EKF stream"
"$PY" scripts/verify_sitl.py --n 1

info "3/5 agent up, measuring default share rate"
scripts/agents.sh 1
sleep 5   # connect + param overlay + first telemetry
m1="$("$PY" scripts/measure_bus.py --seconds 6)"
echo "  $m1"

info "4/5 set_rate 1.0 over the cmd channel, measuring again"
"$PY" - <<'EOF'
from c2.fanout import CmdFanout
fanout = CmdFanout()
fanout.send_rate("all", 1.0)
fanout.close()
EOF
sleep 2
m2="$("$PY" scripts/measure_bus.py --seconds 6)"
echo "  $m2"

info "5/5 asserting"
M1="$m1" M2="$m2" "$PY" - <<'EOF'
import json, os, sys
m1 = json.loads(os.environ["M1"])
m2 = json.loads(os.environ["M2"])
def expect(cond, why):
    if not cond:
        sys.exit(f"SMOKE FAILED: {why}  (m1={m1} m2={m2})")
from common import config
default = config.DEFAULT_RATE_HZ
r1 = m1["state_hz"].get("1")
expect(r1 is not None, "no state messages seen from drone 1")
expect(abs(r1 - default) <= 0.1 * default,
       f"default rate {r1} Hz not within {default}±10%")
expect(m1["rate_applied"].get("1") == default,
       f"telemetry rate_applied != {default}")
r2 = m2["state_hz"].get("1")
expect(r2 is not None and abs(r2 - 1.0) <= 0.1,
       f"post-command rate {r2} Hz not within 1.0±10%")
expect(m2["rate_applied"].get("1") == 1.0,
       "telemetry does not reflect applied rate 1.0")
print(f"SMOKE OK: default {default} Hz measured "
      f"{r1} Hz; after set_rate 1.0 measured {r2} Hz")
EOF

info "smoke test passed"
