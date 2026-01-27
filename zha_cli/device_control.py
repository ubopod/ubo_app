"""Device control for the ZHA CLI."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from zha.application import Platform
from zha.application.platforms import PlatformEntity

if TYPE_CHECKING:
    from zha.zigbee.device import Device

_LOGGER = logging.getLogger(__name__)

# Platforms that support on/off control
CONTROLLABLE_PLATFORMS = {Platform.SWITCH, Platform.LIGHT}


class DeviceController:
    """Controls device entities."""

    @staticmethod
    def get_controllable_entities(device: Device) -> list[PlatformEntity]:
        """Get entities that can be controlled (on/off).

        Args:
            device: The ZHA device.

        Returns:
            List of entities that support turn_on/turn_off.

        """
        entities: list[PlatformEntity] = []

        for (platform, _unique_id), entity in device.platform_entities.items():
            if platform in CONTROLLABLE_PLATFORMS:
                entities.append(entity)

        return entities

    @staticmethod
    def get_all_entities(device: Device) -> list[PlatformEntity]:
        """Get all entities for a device.

        Args:
            device: The ZHA device.

        Returns:
            List of all platform entities.

        """
        return list(device.platform_entities.values())

    @staticmethod
    async def turn_on(entity: PlatformEntity) -> None:
        """Turn on an entity.

        Args:
            entity: The entity to turn on.

        """
        if not hasattr(entity, "async_turn_on"):
            raise ValueError(f"Entity {entity.unique_id} does not support turn_on")

        _LOGGER.info("Turning on entity: %s", entity.unique_id)
        await entity.async_turn_on()
        _LOGGER.info("Entity turned on: %s", entity.unique_id)

    @staticmethod
    async def turn_off(entity: PlatformEntity) -> None:
        """Turn off an entity.

        Args:
            entity: The entity to turn off.

        """
        if not hasattr(entity, "async_turn_off"):
            raise ValueError(f"Entity {entity.unique_id} does not support turn_off")

        _LOGGER.info("Turning off entity: %s", entity.unique_id)
        await entity.async_turn_off()
        _LOGGER.info("Entity turned off: %s", entity.unique_id)

    @staticmethod
    async def toggle(entity: PlatformEntity) -> None:
        """Toggle an entity.

        Args:
            entity: The entity to toggle.

        """
        state = entity.state
        is_on = state.get("state", state.get("on", False))

        if is_on:
            await DeviceController.turn_off(entity)
        else:
            await DeviceController.turn_on(entity)

    @staticmethod
    def get_entity_info(entity: PlatformEntity) -> dict[str, Any]:
        """Get information about an entity.

        Args:
            entity: The entity to get info for.

        Returns:
            Dictionary with entity information.

        """
        return {
            "unique_id": entity.unique_id,
            "platform": entity.PLATFORM,
            "fallback_name": entity.fallback_name,
            "state": entity.state,
            "available": getattr(entity, "available", True),
        }
