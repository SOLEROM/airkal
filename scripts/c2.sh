#!/bin/bash
# Start the C2 server in the background (REST + WebSocket + web page).
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
require_venv
start_daemon "c2" "$PY" -m c2.main --port "$C2_PORT"
info "web page: http://localhost:$C2_PORT"
