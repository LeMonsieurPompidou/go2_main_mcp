#!/bin/sh
# Source-only helper; resolve the mirrored adapter from its configured address.
go2_resolve_interface() {
    go2_lookup_address=$1
    go2_requested_interface=${2:-}
    if [ -n "$go2_requested_interface" ]; then
        go2_addresses=$(ip -o -4 addr show dev "$go2_requested_interface") || return 1
    else
        go2_addresses=$(ip -o -4 addr show) || return 1
    fi
    go2_matching_interfaces=$(printf '%s\n' "$go2_addresses" | awk -v address="$go2_lookup_address" '
        { split($4, parts, "/"); if (parts[1] == address) print $2 }
    ' | sort -u)
    # Interface names cannot contain whitespace.
    set -- $go2_matching_interfaces
    if [ "$#" -ne 1 ]; then
        echo "Expected one WSL interface with $go2_lookup_address. Run Set-Go2Ethernet.ps1 first, or set GO2_NETWORK_INTERFACE explicitly." >&2
        return 1
    fi
    printf '%s\n' "$1"
}
