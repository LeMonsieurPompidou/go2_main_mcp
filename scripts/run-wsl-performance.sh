#!/bin/sh
# Foreground performance launcher using the prepared WSL SDK runtime.
set -eu

go2_rootfs=/var/lib/go2-bridge-runtime/rootfs
go2_address=${GO2_NETWORK_ADDRESS:-192.168.123.100}
go2_repository=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$go2_repository/scripts/go2-network.sh"

if [ ! -x "$go2_rootfs/usr/local/bin/python" ]; then
    echo "Missing prepared Go2 runtime at $go2_rootfs" >&2
    exit 1
fi

# Share the existing bridge's lock: never run two command sources together.
exec 9>/var/lib/go2-bridge-runtime/bridge.lock
if ! flock -n 9; then
    echo 'The bridge or another performance is running. Stop it before starting this routine.' >&2
    exit 1
fi
go2_interface=$(go2_resolve_interface "$go2_address" "${GO2_NETWORK_INTERFACE:-}")
echo "Using WSL interface $go2_interface ($go2_address)"

mountpoint -q "$go2_rootfs/dev" || mount --bind /dev "$go2_rootfs/dev"
mountpoint -q "$go2_rootfs/proc" || mount -t proc proc "$go2_rootfs/proc"
mkdir -p "$go2_rootfs/app/go2_performance"
cp "$go2_repository"/go2_performance/*.py "$go2_rootfs/app/go2_performance/"

exec chroot --userspec=1000:1000 "$go2_rootfs" /usr/bin/env \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    CYCLONEDDS_HOME=/opt/cyclonedds/install \
    GO2_NETWORK_INTERFACE="$go2_interface" \
    GO2_NETWORK_ADDRESS="$go2_address" \
    /usr/local/bin/python -m go2_performance "$@"
