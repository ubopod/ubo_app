# ruff: noqa: D100, D103
"""Device pairing management for the Zigbee service."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from zha.application.const import ZHA_GW_MSG_DEVICE_FULL_INIT, ZHA_GW_MSG_DEVICE_JOINED

from ubo_app.logger import logger

if TYPE_CHECKING:
    from zha.application.gateway import Gateway

DEFAULT_PAIRING_DURATION = 60


class DevicePairingManager:
    """Manages device pairing operations."""

    def __init__(self, gateway: Gateway) -> None:
        """Initialize the pairing manager.

        Args:
            gateway: The ZHA gateway instance.

        """
        self._gateway = gateway
        self._unsubscribe_joined: Callable[[], None] | None = None
        self._unsubscribe_initialized: Callable[[], None] | None = None

    def subscribe_to_events(
        self,
        on_joined: Callable[[Any], None] | None = None,
        on_initialized: Callable[[Any], None] | None = None,
    ) -> Callable[[], None]:
        """Subscribe to device join and initialization events.

        Args:
            on_joined: Callback for when a device joins the network.
            on_initialized: Callback for when a device is fully initialized.

        Returns:
            A function to unsubscribe from all events.

        """
        if on_joined:
            self._unsubscribe_joined = self._gateway.on_event(
                ZHA_GW_MSG_DEVICE_JOINED,
                on_joined,
            )

        if on_initialized:
            self._unsubscribe_initialized = self._gateway.on_event(
                ZHA_GW_MSG_DEVICE_FULL_INIT,
                on_initialized,
            )

        def unsubscribe() -> None:
            if self._unsubscribe_joined:
                self._unsubscribe_joined()
                self._unsubscribe_joined = None
            if self._unsubscribe_initialized:
                self._unsubscribe_initialized()
                self._unsubscribe_initialized = None

        return unsubscribe

    async def enable_pairing(self, duration_s: int = DEFAULT_PAIRING_DURATION) -> None:
        """Enable pairing mode.

        Args:
            duration_s: Duration in seconds to allow pairing.

        """
        logger.info('Enabling pairing mode for %d seconds', duration_s)
        await self._gateway.application_controller.permit(duration_s)
        logger.info('Pairing mode enabled')

    async def disable_pairing(self) -> None:
        """Disable pairing mode."""
        logger.info('Disabling pairing mode')
        await self._gateway.application_controller.permit(0)
        logger.info('Pairing mode disabled')
