# ruff: noqa: D107
"""Sensor view page for the Zigbee service.

Shows live sensor readings for a device.
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from constants import ICON_LOADING, ICON_REFRESH, ICON_SENSOR, ICON_ZIGBEE
from kivy.lang.builder import Builder
from kivy.properties import ListProperty, StringProperty
from redux import AutorunOptions
from ubo_gui.constants import SECONDARY_COLOR_LIGHT
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu

from ubo_app.store.main import store
from ubo_app.store.ubo_actions import register_application
from ubo_app.utils.async_ import create_task
from ubo_app.utils.gui import UboPageWidget

# Grey color for read-only sensor items
SENSOR_ITEM_COLOR = SECONDARY_COLOR_LIGHT

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ubo_app.store.main import RootState
    from ubo_app.store.services.zigbee import ZigbeeEntity


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


def _get_sensor_entities(
    state: RootState,
    device_ieee: str,
) -> Sequence[ZigbeeEntity] | None:
    """Extract sensor entities from state for autorun selector."""
    devices = state.zigbee.devices
    if not devices:
        return None
    for device in devices:
        if device.ieee == device_ieee:
            return tuple(e for e in device.entities if not e.is_controllable)
    return None


def get_sensor_menu(device_ieee: str) -> Callable[[], HeadedMenu | HeadlessMenu]:
    """Get a menu-based sensor view for a device."""

    @store.autorun(
        lambda state: _get_sensor_entities(state, device_ieee),
        options=AutorunOptions(default_value=None),
    )
    def _menu(entities: Sequence[ZigbeeEntity] | None) -> HeadedMenu | HeadlessMenu:
        if entities is None:
            return HeadedMenu(
                title=f'{ICON_ZIGBEE} Sensors',
                heading='Loading...',
                sub_heading='Fetching sensor data',
                items=[],
                placeholder=ICON_LOADING,
            )

        items: list[ActionItem] = []

        if entities:
            items.extend(
                ActionItem(
                    key=entity.unique_id,
                    label=f'{entity.display_name}: {entity.state_display}',
                    icon=ICON_SENSOR,
                    background_color=SENSOR_ITEM_COLOR,
                    action=lambda: None,  # Read-only
                )
                for entity in entities
            )

        # Add refresh option
        items.append(
            ActionItem(
                key='refresh',
                label='Refresh readings',
                icon=ICON_REFRESH,
                action=lambda: _refresh_sensors(device_ieee),
            ),
        )

        return HeadlessMenu(
            title='Sensors',
            items=items,
            placeholder='No sensors',
        )

    return _menu


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
