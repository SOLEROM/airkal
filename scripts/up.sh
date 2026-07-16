#!/bin/bash
# Start N PX4 SITL containers (host networking, per-instance port offsets)
# and wait until each one is answering with MAVLink heartbeats.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

N="${1:-${N:-3}}"
[ "$N" -ge 1 ] 2>/dev/null || die "N must be a positive integer, got '$N'"
require_venv
require_image

for i in $(seq 1 "$N"); do
    name="$CONTAINER_PREFIX-$i"
    if docker inspect "$name" >/dev/null 2>&1; then
        info "$name already exists — skipping (use 'make down' first for a clean start)"
        continue
    fi
    docker run -d --rm --name "$name" --label "$DOCKER_LABEL=1" \
        --network host -e INSTANCE=$((i - 1)) "$IMAGE" >/dev/null
    info "$name started (PX4 instance $((i - 1)), mavlink udp:$((MAVLINK_BASE_PORT + i - 1)))"
done

info "waiting for MAVLink heartbeats ..."
for i in $(seq 1 "$N"); do
    port=$((MAVLINK_BASE_PORT + i - 1))
    "$PY" scripts/wait_mav.py --port "$port" --timeout 60 \
        || die "no heartbeat from instance $i on udp:$port (docker logs $CONTAINER_PREFIX-$i)"
    info "instance $i healthy (udp:$port)"
done
info "all $N SITL instances up"
