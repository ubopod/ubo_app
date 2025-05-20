"""Module for sending commands to the system manager socket."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal, overload

from ubo_app.constants import SERVER_SOCKET_PATH
from ubo_app.logger import logger
from ubo_app.utils import IS_RPI

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@overload
async def send_command(*command: str) -> None: ...
@overload
async def send_command(
    *command: str,
    has_output: Literal[True],
) -> str: ...
@overload
async def send_command(
    *command: str,
    has_output_stream: Literal[True],
) -> AsyncIterator[str]: ...
async def send_command(
    *command_: str,
    has_output: bool = False,
    has_output_stream: bool = False,
) -> AsyncIterator[str] | str | None:
    """Send a command to the system manager socket."""
    if not IS_RPI:
        return None

    command = ' '.join(command_)

    try:
        reader, writer = await asyncio.open_unix_connection(SERVER_SOCKET_PATH)

        logger.debug('Sending command:', extra={'command': command})

        writer.write(command.encode() + b'\0')
        if has_output:
            response = ''
            datagram = (await reader.readuntil(b'\0'))[:-1]
            if datagram:
                response = datagram.decode('utf-8')
                logger.debug('Server response:', extra={'response': response})

            writer.close()
            return response

        if has_output_stream:

            async def generator() -> AsyncIterator[str]:
                while datagram := (await reader.readuntil(b'\0'))[:-1]:
                    yield datagram.decode('utf-8')
                    logger.debug(
                        'Server response:',
                        extra={
                            'command': command,
                            'response': datagram.decode('utf-8'),
                        },
                    )

                writer.close()

            return generator()

    except Exception:
        logger.exception(
            'Failed to send command to the server',
            extra={'command': command},
        )
        raise
