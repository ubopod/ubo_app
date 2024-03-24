"""Module for sending commands to the system manager socket."""

from __future__ import annotations

import socket
import threading
from typing import Literal, overload

from ubo_app.constants import SOCKET_PATH
from ubo_app.logging import logger

thread_lock = threading.Lock()


@overload
def send_command(command: str) -> None: ...


@overload
def send_command(command: str, *, has_output: Literal[True]) -> str: ...


def send_command(command: str, *, has_output: bool = False) -> str | None:
    """Send a command to the system manager socket."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(SOCKET_PATH)
    except Exception as exception:  # noqa: BLE001
        logger.error('Unable to connect to the socket', exc_info=exception)
        if has_output:
            return ''
        return None

    output = None
    with thread_lock:
        client.sendall(f'{command}'.encode() + b'\0')
        remaining = b''
        while has_output:
            datagram = remaining + client.recv(1024)
            if not datagram:
                break
            if b'\0' not in datagram:
                remaining = datagram
                continue
            response, remaining = datagram.split(b'\0', 1)
            output = response.decode('utf-8')
            logger.debug('Server response:', extra={'response': response})
        client.close()

    return output
