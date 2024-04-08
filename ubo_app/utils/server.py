"""Module for sending commands to the system manager socket."""

from __future__ import annotations

import asyncio
import threading
from typing import Literal, overload

from ubo_app.constants import SERVER_SOCKET_PATH
from ubo_app.logging import logger
from ubo_app.utils import IS_RPI

thread_lock = threading.Lock()


@overload
async def send_command(command: str) -> None: ...


@overload
async def send_command(command: str, *, has_output: Literal[True]) -> str: ...


async def send_command(command: str, *, has_output: bool = False) -> str | None:
    """Send a command to the system manager socket."""
    if not IS_RPI:
        return None
    reader, writer = await asyncio.open_unix_connection(SERVER_SOCKET_PATH)

    logger.debug('Sending command:', extra={'command': command})

    response = None
    with thread_lock:
        writer.write(f'{command}'.encode() + b'\0')
        while has_output:
            datagram = (await reader.readuntil(b'\0'))[:-1]
            if not datagram:
                break
            response = datagram.decode('utf-8')
            logger.debug('Server response:', extra={'response': response})
        writer.close()
        await writer.wait_closed()

    logger.debug('Received response:', extra={'response': response})

    return response
