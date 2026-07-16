#!/bin/bash
# Start N agents in the background, one per SITL instance.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

N="${1:-${N:-3}}"
[ "$N" -ge 1 ] 2>/dev/null || die "N must be a positive integer, got '$N'"
require_venv

for i in $(seq 1 "$N"); do
    start_daemon "agent-$i" "$PY" -m agent.main --id "$i" \
        --param-file sitl/params.override
done
