#!/bin/sh
# Start one headless PX4 SITL instance using the SIH (simulation-in-hardware)
# quadcopter model: the vehicle dynamics run inside PX4 itself, so no external
# simulator process is needed and the container stays small and deterministic.
#
# Env:
#   INSTANCE          0-based PX4 instance number (port offsets, MAV_SYS_ID).
#   PX4_SYS_AUTOSTART airframe id override; auto-detected from the build if unset.
#   PX4_SIM_MODEL     model name override (default sihsim_quadx).
set -eu

: "${INSTANCE:=0}"
BUILD=/px4/build/px4_sitl_default
AIRFRAMES="$BUILD/etc/init.d-posix/airframes"

# Resolve the SIH quadcopter airframe id from the pinned build so a PX4
# version bump cannot silently break the entrypoint.
if [ -z "${PX4_SYS_AUTOSTART:-}" ]; then
    af="$(ls "$AIRFRAMES" | grep 'sihsim_quadx$' | head -n 1 || true)"
    if [ -z "$af" ]; then
        echo "entrypoint: no *sihsim_quadx airframe under $AIRFRAMES" >&2
        echo "entrypoint: set PX4_SYS_AUTOSTART explicitly" >&2
        exit 1
    fi
    PX4_SYS_AUTOSTART="${af%%_*}"
fi
export PX4_SYS_AUTOSTART
export PX4_SIM_MODEL="${PX4_SIM_MODEL:-sihsim_quadx}"

# Per-instance writable working directory (parameters, dataman, logs).
work="/px4/rootfs/$INSTANCE"
mkdir -p "$work"
cd "$work"

echo "entrypoint: instance=$INSTANCE autostart=$PX4_SYS_AUTOSTART model=$PX4_SIM_MODEL"
exec "$BUILD/bin/px4" -d -i "$INSTANCE" -s etc/init.d-posix/rcS "$BUILD/etc"
