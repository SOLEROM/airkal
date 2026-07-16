#!/bin/bash
# Show what is running and on which ports.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

echo "── SITL containers ──────────────────────────────────────────"
docker ps --filter "label=$DOCKER_LABEL" \
    --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' 2>/dev/null \
    | sed '1!s/^/  /' || echo "  (docker unavailable)"

echo "── host processes ───────────────────────────────────────────"
found=0
for pidfile in "$VAR_RUN"/*.pid; do
    [ -e "$pidfile" ] || continue
    name="$(basename "$pidfile" .pid)"
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
        echo "  $name: running (pid $pid)"
    else
        echo "  $name: DEAD (stale pidfile)"
    fi
    found=1
done
[ "$found" = 1 ] || echo "  (none)"

echo "── ports ────────────────────────────────────────────────────"
echo "  UDP channels: state 48000, cmd 48010, telemetry 48020, stats 48030"
echo "  MAVLink: udp 14540+i per instance;  C2 web: http://localhost:$C2_PORT"
if command -v curl >/dev/null; then
    if curl -sf -m 2 "http://localhost:$C2_PORT/api/fleet" >/dev/null 2>&1; then
        echo "  C2 API: responding"
    else
        echo "  C2 API: not responding"
    fi
fi
