"""Launch a stationary nodding performance, or preview it without the SDK."""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import signal
import sys
import threading

from .routine import Plan, run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=180, help="1-180 seconds (default: 180)")
    parser.add_argument("--period", type=float, default=4, help="seconds per nod (default: 4)")
    parser.add_argument("--pitch-deg", type=float, default=1.5, help="maximum tilt; hard limit 2 degrees")
    parser.add_argument("--clearance-cm", type=float, default=10, help="measured minimum gap in the starting standing pose")
    parser.add_argument("--interface", default=os.getenv("GO2_NETWORK_INTERFACE", "eno1"))
    parser.add_argument("--address", default=os.getenv("GO2_NETWORK_ADDRESS", ""), help="local adapter IPv4 address, not robot IP")
    parser.add_argument("--dry-run", action="store_true", help="print the plan without loading the SDK or moving")
    args = parser.parse_args(argv)
    try:
        plan = Plan(args.duration, args.period, args.pitch_deg, args.clearance_cm)
        if args.address:
            ipaddress.IPv4Address(args.address)
    except ValueError as exc:
        parser.error(str(exc))

    print(json.dumps(plan.summary(), indent=2), flush=True)
    print("Clearance is a planning estimate; there is no distance sensor or collision guarantee.", flush=True)
    if args.dry_run:
        print("DRY RUN: no SDK loaded, no robot connection, no movement.", flush=True)
        return 0

    cancelled = threading.Event()

    def request_stop(signum, frame):
        cancelled.set()

    previous_handlers = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[sig] = signal.signal(sig, request_stop)
    try:
        print("Only the moving robot may share this adapter's DDS network.", flush=True)
        print("Starting in 5 seconds. Ctrl+C cancels. Keep a physical stop available.", flush=True)
        if cancelled.wait(5):
            return 130

        # Deliberately lazy: offline preview and timing tests do not need DDS.
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        from unitree_sdk2py.go2.sport.sport_client import SportClient
        from go2_bridge.robot import _pin_network_address

        if args.address:
            _pin_network_address(args.address)
        ChannelFactoryInitialize(0, args.interface)
        sport = SportClient()
        sport.SetTimeout(3.0)
        sport.Init()
        result = run(sport, plan, cancelled, report=lambda message: print(message, flush=True))
        print(f"Performance {result}.", flush=True)
        return 0 if result == "completed" else 130
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
