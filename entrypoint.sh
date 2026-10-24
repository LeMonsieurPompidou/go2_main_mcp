#!/usr/bin/env bash
# Container entrypoint — dispatches to the component named by the first arg.
# All components read their config from env vars (see .env.example).
set -e

case "$1" in
    bridge)
        shift
        exec python -m go2_bridge "$@"
        ;;
    webapp)
        shift
        exec python -m go2_webapp "$@"
        ;;
    mcp)
        shift
        exec python -m go2_mcp "$@"
        ;;
    cli)
        shift
        exec python go2_client/cli_client.py "$@"
        ;;
    bash|sh)
        exec "$@"
        ;;
    *)
        exec "$@"
        ;;
esac
