# ruff: noqa: D100, D101, D102, D103, D104, D105, D107
from __future__ import annotations

import socket
from pathlib import Path

from ubo_app.logging import logger
from ubo_app.store import dispatch
from ubo_app.store.services.rgb_ring import RgbRingSetIsConnectedAction

LM_SOCKET_PATH = Path('/run/ubo').joinpath('ledmanagersocket.sock').as_posix()


class RgbRingClient:
    """The instances of this class send commands to the LED manager.

    The LED Manager runs with root privileges due to hardware DMA security constraints.
    The commands are sent through a socket connection to the LED manager.

    The LED manager is a Python script that runs as a daemon. The LED manager
    is a daemon because it uses DMA to control the LEDs. This is a hardware security
    constraint.

    The LED client is a Python script that runs as a non-root user. The LED client
    function is to serialize LED commands and send them to the LED manager in a secure
    manner.
    """

    def __init__(self: RgbRingClient) -> None:
        self.server_socket: socket.SocketType | None = None
        if Path(LM_SOCKET_PATH).exists():
            self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                self.server_socket.connect(LM_SOCKET_PATH)
                dispatch(RgbRingSetIsConnectedAction(is_connected=True))
            except Exception as exception:  # noqa: BLE001
                dispatch(RgbRingSetIsConnectedAction(is_connected=False))
                logger.error('Unable to connect to the socket', exc_info=exception)
                return

    def __del__(self: RgbRingClient) -> None:
        if self.server_socket is not None:
            self.server_socket.close()

    def send(self: RgbRingClient, cmd: str) -> None:
        if not self.server_socket:
            return
        self.server_socket.send(cmd.encode('utf-8'))
