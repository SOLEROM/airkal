#!/bin/bash
# Stop everything: host processes first, then all demo containers.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

for pidfile in "$VAR_RUN"/*.pid; do
    [ -e "$pidfile" ] || continue
    stop_daemon "$(basename "$pidfile" .pid)"
done

containers="$(docker ps -aq --filter "label=$DOCKER_LABEL" 2>/dev/null || true)"
if [ -n "$containers" ]; then
    docker rm -f $containers >/dev/null
    info "removed $(echo "$containers" | wc -l) SITL container(s)"
else
    info "no SITL containers running"
fi
info "down complete"
