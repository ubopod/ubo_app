"""Device pairing management for the ZHA CLI."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
from typing import TYPE_CHECKING, Any

from zha.application.const import ZHA_GW_MSG_DEVICE_FULL_INIT, ZHA_GW_MSG_DEVICE_JOINED

if TYPE_CHECKING:
    from zha.application.gateway import Gateway

_LOGGER = logging.getLogger(__name__)

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
        self._pairing_active = False

    @property
    def is_pairing_active(self) -> bool:
        """Return True if pairing mode is active."""
        return self._pairing_active

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
        _LOGGER.info("Enabling pairing mode for %d seconds", duration_s)
        await self._gateway.application_controller.permit(duration_s)
        self._pairing_active = True
        _LOGGER.info("Pairing mode enabled")

    async def disable_pairing(self) -> None:
        """Disable pairing mode."""
        _LOGGER.info("Disabling pairing mode")
        await self._gateway.application_controller.permit(0)
        self._pairing_active = False
        _LOGGER.info("Pairing mode disabled")

    async def wait_for_device(
        self,
        timeout_s: int = DEFAULT_PAIRING_DURATION,
    ) -> Any | None:
        """Wait for a device to be fully initialized.

        Args:
            timeout_s: Maximum time to wait in seconds.

        Returns:
            The device initialization event, or None if timeout.

        """
        event_received = asyncio.Event()
        device_event: list[Any] = []

        def on_initialized(event: Any) -> None:
            device_event.append(event)
            event_received.set()

        unsubscribe = self.subscribe_to_events(on_initialized=on_initialized)

        try:
            await asyncio.wait_for(event_received.wait(), timeout=timeout_s)
            return device_event[0] if device_event else None
        except TimeoutError:
            _LOGGER.debug("Timeout waiting for device")
            return None
        finally:
            unsubscribe()
