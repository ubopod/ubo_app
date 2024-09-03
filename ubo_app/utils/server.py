"""Module for sending commands to the system manager socket."""

from __future__ import annotations

import asyncio
from typing import Literal, overload

from ubo_app.constants import SERVER_SOCKET_PATH
from ubo_app.logging import logger
from ubo_app.utils import IS_RPI


@overload
async def send_command(*command: str) -> None: ...
@overload
async def send_command(*command: str, has_output: Literal[True]) -> str | None: ...
async def send_command(*command_: str, has_output: bool = False) -> str | None:
    """Send a command to the system manager socket."""
    if not IS_RPI:
        return None

    command = ' '.join(command_)

    try:
        reader, writer = await asyncio.open_unix_connection(SERVER_SOCKET_PATH)

        logger.info('Sending command:', extra={'command': command})

        response = None
        writer.write(command.encode() + b'\0')
        if has_output:
            datagram = (await reader.readuntil(b'\0'))[:-1]
            if datagram:
                response = datagram.decode('utf-8')
                logger.info('Server response:', extra={'response': response})
        writer.close()

    except Exception:
        logger.exception('Failed to send command to the server')
        raise
    else:
        return response
