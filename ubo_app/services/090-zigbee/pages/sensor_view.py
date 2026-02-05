# ruff: noqa: D100, D101, D102, D107
"""Sensor view page for the Zigbee service.

Shows live sensor readings for a device.
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from constants import ICON_REFRESH, ICON_SENSOR
from kivy.lang.builder import Builder
from kivy.properties import ListProperty, StringProperty
from ubo_gui.menu.types import ActionItem, HeadlessMenu

from ubo_app.store.main import store
from ubo_app.store.ubo_actions import register_application
from ubo_app.utils.async_ import create_task
from ubo_app.utils.gui import UboPageWidget

if TYPE_CHECKING:
    pass


class SensorViewPage(UboPageWidget):
    """Page showing sensor readings for a device."""

    device_ieee: str = StringProperty('')
    device_name: str = StringProperty('')
    sensor_readings: list = ListProperty([])

    def __init__(self, device_ieee: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.device_ieee = device_ieee
        self._load_sensors()

    def _load_sensors(self) -> None:
        """Load sensor data from the device."""
        from setup import get_network_manager
        from zigbee import DeviceController

        manager = get_network_manager()
        device_info = manager.get_device_by_ieee(self.device_ieee)

        if not device_info:
            self.device_name = 'Device Not Found'
            return

        self.device_name = device_info['name']
        device = device_info['device']

        # Get monitorable entities
        entities = DeviceController.get_monitorable_entities(device)

        readings = []
        for entity in entities:
            name = DeviceController.get_display_name(entity)
            state = DeviceController.format_entity_state(entity)
            readings.append({'name': name, 'value': state, 'entity': entity})

        self.sensor_readings = readings

    def refresh_sensors(self) -> None:
        """Refresh all sensor readings from the device."""
        from zigbee import DeviceController

        async def _do_refresh() -> None:
            for reading in self.sensor_readings:
                entity = reading.get('entity')
                if entity:
                    await DeviceController.refresh_entity(entity, timeout=5.0)

            # Reload sensor data
            self._load_sensors()

        create_task(_do_refresh())


register_application(
    application=SensorViewPage,
    application_id='zigbee:sensor-view',
)


def get_sensor_menu(device_ieee: str) -> HeadlessMenu:
    """Get a menu-based sensor view for a device."""
    from setup import get_network_manager
    from zigbee import DeviceController

    manager = get_network_manager()
    device_info = manager.get_device_by_ieee(device_ieee)

    if not device_info:
        return HeadlessMenu(
            title='Sensors',
            items=[],
            placeholder='Device not found',
        )

    device = device_info['device']
    device_name = device_info['name']
    entities = DeviceController.get_monitorable_entities(device)

    items: list[ActionItem] = []

    for entity in entities:
        name = DeviceController.get_display_name(entity)
        state = DeviceController.format_entity_state(entity)
        items.append(
            ActionItem(
                key=entity.unique_id,
                label=f'{name}: {state}',
                icon=ICON_SENSOR,
                action=lambda: None,  # Read-only
            )
        )

    # Add refresh option
    items.append(
        ActionItem(
            key='refresh',
            label='Refresh readings',
            icon=ICON_REFRESH,
            action=lambda: _refresh_sensors(device_ieee),
        )
    )

    return HeadlessMenu(
        title=f'{device_name} Sensors',
        items=items,
    )


def _refresh_sensors(device_ieee: str) -> None:
    """Refresh sensor readings for a device."""
    from setup import get_network_manager
    from zigbee import DeviceController

    async def _do_refresh() -> None:
        manager = get_network_manager()
        device_info = manager.get_device_by_ieee(device_ieee)

        if not device_info:
            return

        device = device_info['device']
        entities = DeviceController.get_monitorable_entities(device)

        for entity in entities:
            await DeviceController.refresh_entity(entity, timeout=5.0)

    create_task(_do_refresh())


Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('sensor_view.kv')
    .resolve()
    .as_posix(),
)
