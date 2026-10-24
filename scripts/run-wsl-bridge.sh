#!/bin/sh
# Run the exported Go2 image's installed runtime on WSL's mirrored network.
# Prepare rootfs with docker export + tar; run this script as root in Ubuntu.
set -eu

go2_rootfs=/var/lib/go2-bridge-runtime/rootfs
go2_interface=${GO2_NETWORK_INTERFACE:-eth3}
go2_address=${GO2_NETWORK_ADDRESS:-192.168.123.100}

exec 9>/var/lib/go2-bridge-runtime/bridge.lock
if ! flock -n 9; then
    echo 'A WSL Go2 bridge is already running' >&2
    exit 1
fi

if [ ! -x "$go2_rootfs/usr/local/bin/python" ]; then
    echo "Missing exported Go2 runtime at $go2_rootfs" >&2
    exit 1
fi
case "$(ip -o -4 addr show dev "$go2_interface")" in
    *" $go2_address/"*) ;;
    *) echo "$go2_interface does not have $go2_address; configure the host Ethernet adapter first" >&2; exit 1 ;;
esac

# The runtime needs the native system's devices and process/network metadata.
mountpoint -q "$go2_rootfs/dev" || mount --bind /dev "$go2_rootfs/dev"
mountpoint -q "$go2_rootfs/proc" || mount -t proc proc "$go2_rootfs/proc"
cd "$go2_rootfs/app"
exec chroot --userspec=1000:1000 "$go2_rootfs" /usr/bin/env \
    PYTHONUNBUFFERED=1 \
    CYCLONEDDS_HOME=/opt/cyclonedds/install \
    GO2_NETWORK_INTERFACE="$go2_interface" \
    GO2_NETWORK_ADDRESS="$go2_address" \
    GO2_ZMQ_CMD_PORT=5555 \
    GO2_ZMQ_PUB_PORT=5556 \
    GO2_OBSTACLE_AVOIDANCE=1 \
    /bin/sh -c 'cd /app && exec /usr/local/bin/python -m go2_bridge'
