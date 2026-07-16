#!/bin/bash
# Start netstats in the background (quiet: publishes on the stats channel
# only — run 'make stats' in a terminal for the live table view).
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
require_venv
start_daemon "netstats" "$PY" -m netstats.main --quiet
