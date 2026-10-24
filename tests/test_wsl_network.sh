#!/bin/sh
set -eu
go2_test_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$go2_test_dir/../scripts/go2-network.sh"

# Fake ip output, including a changed WSL interface number.
ip() {
    if [ "$#" -eq 6 ]; then
        printf '%s\n' "$go2_fixture" | awk -v name="$6" '$2 == name'
    else
        printf '%s\n' "$go2_fixture"
    fi
}
go2_fixture='2: eth2 inet 10.4.24.245/23 scope global eth2
8: eth8 inet 192.168.123.100/24 scope global eth8'
[ "$(go2_resolve_interface 192.168.123.100)" = eth8 ]
[ "$(go2_resolve_interface 192.168.123.100 eth8)" = eth8 ]
if go2_resolve_interface 192.168.123.100 eth3 >/dev/null 2>&1; then exit 1; fi
if go2_resolve_interface 192.168.123.99 >/dev/null 2>&1; then exit 1; fi
go2_fixture="$go2_fixture
9: eth9 inet 192.168.123.100/24 scope global eth9"
if go2_resolve_interface 192.168.123.100 >/dev/null 2>&1; then exit 1; fi
[ "$(go2_resolve_interface 192.168.123.100 eth9)" = eth9 ]
printf '%s\n' 'PASS: 6 WSL interface-resolution checks; no network settings changed.'
