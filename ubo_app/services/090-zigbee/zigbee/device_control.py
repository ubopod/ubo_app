# ruff: noqa: D100, D103
"""Device control for the Zigbee service."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from zha.application import Platform
from zha.application.platforms import PlatformEntity

from ubo_app.logger import logger

if TYPE_CHECKING:
    from zha.zigbee.device import Device

# Unit display mapping for common sensor units
# Maps raw unit strings to nice display format with proper symbols
UNIT_DISPLAY = {
    # Temperature
    '°C': '°C',
    'C': '°C',
    'celsius': '°C',
    '°F': '°F',
    'F': '°F',
    'fahrenheit': '°F',
    'K': 'K',
    'kelvin': 'K',
    # Percentage
    '%': '%',
    'percent': '%',
    # Power
    'W': 'W',
    'kW': 'kW',
    'mW': 'mW',
    # Energy
    'Wh': 'Wh',
    'kWh': 'kWh',
    # Voltage
    'V': 'V',
    'mV': 'mV',
    # Current
    'A': 'A',
    'mA': 'mA',
    # Pressure
    'hPa': 'hPa',
    'kPa': 'kPa',
    'Pa': 'Pa',
    'mbar': 'mbar',
    # Illuminance
    'lx': 'lx',
    'lm': 'lm',
    # Signal
    'dB': 'dB',
    'dBm': 'dBm',
    # Concentration
    'ppm': 'ppm',
    'ppb': 'ppb',
    'µg/m³': 'µg/m³',
    'mg/m³': 'mg/m³',
}


def _format_unit(unit: str | None) -> str:
    """Format a unit string with proper display symbols.

    Args:
        unit: The raw unit string from the entity.

    Returns:
        Formatted unit string with proper symbols.

    """
    if not unit:
        return ''
    # Look up in display mapping, or return as-is
    return UNIT_DISPLAY.get(unit, unit)


# Platforms that support on/off control
CONTROLLABLE_PLATFORMS = {Platform.SWITCH, Platform.LIGHT}

# Platforms that are monitorable (read-only sensors and status)
MONITORABLE_PLATFORMS = {
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.EVENT,
}


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
    def get_monitorable_entities(device: Device) -> list[PlatformEntity]:
        """Get entities that can be monitored (sensors, binary sensors, etc.).

        Args:
            device: The ZHA device.

        Returns:
            List of entities that report state but can't be controlled.

        """
        entities: list[PlatformEntity] = []

        for (platform, _unique_id), entity in device.platform_entities.items():
            if platform in MONITORABLE_PLATFORMS:
                entities.append(entity)

        return entities

    @staticmethod
    def format_entity_state(entity: PlatformEntity) -> str:
        """Format entity state for display.

        Args:
            entity: The entity to format.

        Returns:
            Human-readable state string.

        """
        platform = entity.PLATFORM

        # Binary sensor
        if platform == Platform.BINARY_SENSOR:
            is_on = entity.state.get('state', False)
            return 'Detected' if is_on else 'Clear'

        # Regular sensor - use native_value property directly
        if platform == Platform.SENSOR:
            value = getattr(entity, 'native_value', None)
            if value is not None:
                # Try multiple sources for unit:
                # 1. info_object.unit (primary source for ZHA sensors)
                # 2. Direct attributes
                # 3. State dict
                raw_unit = None
                info_obj = getattr(entity, 'info_object', None)
                if info_obj is not None:
                    raw_unit = getattr(info_obj, 'unit', None)
                if not raw_unit:
                    raw_unit = (
                        getattr(entity, '_attr_native_unit_of_measurement', None)
                        or getattr(entity, 'native_unit_of_measurement', None)
                        or entity.state.get('unit_of_measurement')
                    )
                unit = _format_unit(raw_unit)
                if unit:
                    return f'{value} {unit}'
                return str(value)
            return 'Waiting...'

        # Device tracker
        if platform == Platform.DEVICE_TRACKER:
            connected = entity.state.get('connected')
            if connected is not None:
                return str(connected)
            return 'Waiting...'

        # Event - show last event type
        if platform == Platform.EVENT:
            event_type = entity.state.get('event_type')
            if event_type is not None:
                return f'Last: {event_type}'
            return 'No events'

        # Fallback - show raw state or dash
        state = entity.state
        if not state:
            return 'Waiting...'
        return str(state)

    @staticmethod
    async def refresh_entity(entity: PlatformEntity, timeout: float = 5.0) -> bool:
        """Refresh entity state from device via ZCL Read Attributes.

        Args:
            entity: The entity to refresh.
            timeout: Maximum seconds to wait for device response.

        Returns:
            True if refresh succeeded, False if it failed (e.g., timeout).

        """
        # Get the primary attribute and cluster handler for sensor entities
        attribute_name = getattr(entity, '_attribute_name', None)
        cluster_handler = getattr(entity, '_cluster_handler', None)

        if attribute_name and cluster_handler:
            try:
                await asyncio.wait_for(
                    cluster_handler.get_attribute_value(
                        attribute_name,
                        from_cache=False,
                    ),
                    timeout=timeout,
                )
                return True
            except asyncio.TimeoutError:
                logger.debug(
                    'Timeout reading %s from %s (battery device?)',
                    attribute_name,
                    entity.unique_id,
                )
                return False
            except Exception as ex:
                logger.debug(
                    'Failed to read %s from %s: %s',
                    attribute_name,
                    entity.unique_id,
                    ex,
                )
                return False

        # Fallback for entities without _attribute_name
        if hasattr(entity, 'async_update'):
            try:
                await asyncio.wait_for(entity.async_update(), timeout=timeout)
            except Exception:
                return False
        return True

    @staticmethod
    def get_display_name(entity: PlatformEntity) -> str:
        """Get a user-friendly display name for an entity.

        Uses fallback_name if available, otherwise generates a name from
        device_class or platform type.

        Args:
            entity: The entity to get a name for.

        Returns:
            Human-readable display name.

        """
        # 1. Use fallback_name if available and not "None"
        if entity.fallback_name and entity.fallback_name != 'None':
            return entity.fallback_name

        # 2. Use device_class if available (title-cased)
        device_class = getattr(entity, 'device_class', None)
        if device_class:
            # Handle enum values or strings
            class_name = (
                device_class.value
                if hasattr(device_class, 'value')
                else str(device_class)
            )
            return class_name.replace('_', ' ').title()

        # 3. Fall back to platform type
        platform = entity.PLATFORM
        if hasattr(platform, 'value'):
            return platform.value.replace('_', ' ').title()
        return str(platform).title()

    @staticmethod
    async def turn_on(entity: PlatformEntity) -> None:
        """Turn on an entity.

        Args:
            entity: The entity to turn on.

        """
        if not hasattr(entity, 'async_turn_on'):
            msg = f'Entity {entity.unique_id} does not support turn_on'
            raise ValueError(msg)

        logger.info('Turning on entity: %s', entity.unique_id)
        await entity.async_turn_on()
        logger.info('Entity turned on: %s', entity.unique_id)

    @staticmethod
    async def turn_off(entity: PlatformEntity) -> None:
        """Turn off an entity.

        Args:
            entity: The entity to turn off.

        """
        if not hasattr(entity, 'async_turn_off'):
            msg = f'Entity {entity.unique_id} does not support turn_off'
            raise ValueError(msg)

        logger.info('Turning off entity: %s', entity.unique_id)
        await entity.async_turn_off()
        logger.info('Entity turned off: %s', entity.unique_id)

    @staticmethod
    async def toggle(entity: PlatformEntity) -> None:
        """Toggle an entity.

        Args:
            entity: The entity to toggle.

        """
        state = entity.state
        # Switch uses "state" key, Light uses "on" key
        is_on = state.get('state') if 'state' in state else state.get('on', False)

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
            'unique_id': entity.unique_id,
            'platform': entity.PLATFORM,
            'fallback_name': entity.fallback_name,
            'display_name': DeviceController.get_display_name(entity),
            'state': entity.state,
            'available': getattr(entity, 'available', True),
        }
