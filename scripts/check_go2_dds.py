"""Verify incoming Go2 telemetry without sending a motion command."""

import threading

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_

from go2_bridge import config
from go2_bridge.robot import _pin_network_address


def main():
    if config.NETWORK_ADDRESS:
        _pin_network_address(config.NETWORK_ADDRESS)
    ChannelFactoryInitialize(0, config.NETWORK_INTERFACE)
    received = threading.Event()

    def on_state(state):
        if not received.is_set():
            print(f"Robot telemetry received: mode={state.mode}, position={state.position}", flush=True)
            received.set()

    subscriber = ChannelSubscriber("rt/sportmodestate", SportModeState_)
    subscriber.Init(on_state, 10)
    try:
        if not received.wait(10):
            raise SystemExit("No robot DDS telemetry within 10 seconds")
    finally:
        subscriber.Close()


if __name__ == "__main__":
    main()
