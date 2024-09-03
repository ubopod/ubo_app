# ruff: noqa: D100, D101, D102, D103, D104, D105, D107
from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.logging import logger
from ubo_app.store.main import store
from ubo_app.store.services.rgb_ring import RgbRingSetIsConnectedAction
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from collections.abc import Sequence


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

    async def send(self: RgbRingClient, cmd: Sequence[str]) -> None:
        try:
            await send_command('led', *cmd)
            store.dispatch(RgbRingSetIsConnectedAction(is_connected=True))
        except Exception:
            store.dispatch(RgbRingSetIsConnectedAction(is_connected=False))
            logger.exception('Unable to connect to the socket')
