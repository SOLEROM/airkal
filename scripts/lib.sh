#!/bin/bash
# Shared helpers for the lifecycle scripts. Expects to be sourced with the
# Makefile-exported env: IMAGE, N, C2_PORT, PY, ROOT.
set -euo pipefail

ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${PY:-$ROOT/.venv/bin/python}"
IMAGE="${IMAGE:-airkal-sitl:$(cat "$ROOT/sitl/VERSION" | tr -d '[:space:]')}"
C2_PORT="${C2_PORT:-8080}"

VAR_LOG="$ROOT/var/log"
VAR_RUN="$ROOT/var/run"
CONTAINER_PREFIX="airkal-sitl"
DOCKER_LABEL="airkal-demo"
MAVLINK_BASE_PORT=14540

mkdir -p "$VAR_LOG" "$VAR_RUN"
cd "$ROOT"

die() { echo "error: $*" >&2; exit 1; }
info() { echo "[$(basename "$0")] $*"; }

require_venv() {
    [ -x "$PY" ] || die "no venv at $PY — run 'make install' first"
}

require_image() {
    docker image inspect "$IMAGE" >/dev/null 2>&1 \
        || die "image $IMAGE not found — run 'make build' first"
}

# start_daemon NAME CMD...  → background process, pidfile, log file
start_daemon() {
    local name="$1"; shift
    local pidfile="$VAR_RUN/$name.pid"
    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        info "$name already running (pid $(cat "$pidfile"))"
        return 0
    fi
    nohup "$@" > "$VAR_LOG/$name.log" 2>&1 &
    echo $! > "$pidfile"
    info "$name started (pid $!, log var/log/$name.log)"
}

stop_daemon() {
    local name="$1"
    local pidfile="$VAR_RUN/$name.pid"
    [ -f "$pidfile" ] || return 0
    local pid
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        for _ in $(seq 1 20); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.1
        done
        kill -9 "$pid" 2>/dev/null || true
        info "$name stopped (pid $pid)"
    fi
    rm -f "$pidfile"
}
