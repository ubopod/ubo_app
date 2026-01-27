"""Network management for the ZHA CLI."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from zha.application.gateway import Gateway
from zha.application.helpers import CoordinatorConfiguration, ZHAConfiguration, ZHAData

if TYPE_CHECKING:
    from zha.cli.coordinator_probe import DetectedCoordinator

_LOGGER = logging.getLogger(__name__)


class NetworkManager:
    """Manages the Zigbee network lifecycle."""

    def __init__(self) -> None:
        """Initialize the network manager."""
        self._gateway: Gateway | None = None
        self._coordinator: DetectedCoordinator | None = None

    @property
    def gateway(self) -> Gateway | None:
        """Return the current gateway."""
        return self._gateway

    @property
    def coordinator(self) -> DetectedCoordinator | None:
        """Return the current coordinator."""
        return self._coordinator

    @property
    def is_running(self) -> bool:
        """Return True if the network is running."""
        return self._gateway is not None and not self._gateway.shutting_down

    async def start_network(self, coordinator: DetectedCoordinator) -> Gateway:
        """Start the Zigbee network with the specified coordinator.

        Creates a ZHAData configuration and initializes the gateway.

        Args:
            coordinator: The detected coordinator to use.

        Returns:
            The initialized Gateway instance.

        Raises:
            Exception: If the gateway fails to initialize.

        """
        if self._gateway is not None:
            _LOGGER.warning("Network already running, shutting down first")
            await self.shutdown()

        _LOGGER.info(
            "Starting network with %s at %s (%d baud)",
            coordinator.radio_type.pretty_name,
            coordinator.port,
            coordinator.baudrate,
        )

        # Create the configuration
        coordinator_config = CoordinatorConfiguration(
            path=coordinator.port,
            baudrate=coordinator.baudrate,
            radio_type=coordinator.radio_type.name,
        )

        zha_config = ZHAConfiguration(
            coordinator_configuration=coordinator_config,
        )

        zha_data = ZHAData(config=zha_config)

        # Create and initialize the gateway
        self._gateway = await Gateway.async_from_config(zha_data)
        await self._gateway.async_initialize()

        self._coordinator = coordinator

        _LOGGER.info("Network started successfully")
        return self._gateway

    async def shutdown(self) -> None:
        """Shut down the Zigbee network."""
        if self._gateway is None:
            _LOGGER.debug("No network to shut down")
            return

        _LOGGER.info("Shutting down network")
        await self._gateway.shutdown()
        self._gateway = None
        self._coordinator = None
        _LOGGER.info("Network shut down successfully")

    def get_devices(self) -> list[dict]:
        """Get all paired devices.

        Returns:
            List of device info dictionaries.

        """
        if self._gateway is None:
            return []

        devices = []
        for device in self._gateway.devices.values():
            # Skip the coordinator
            if device.is_coordinator:
                continue

            devices.append(
                {
                    "ieee": device.ieee,
                    "nwk": device.nwk,
                    "manufacturer": device.manufacturer,
                    "model": device.model,
                    "name": device.name,
                    "available": device.available,
                    "device": device,
                }
            )

        return devices
