# ruff: noqa: D107
"""Device control page for the Zigbee service.

Shows device details and controls for a specific device.
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from constants import (
    ICON_DELETE,
    ICON_LIGHT,
    ICON_LOADING,
    ICON_RENAME,
    ICON_SENSOR,
    ICON_SWITCH,
    ICON_ZIGBEE,
)
from kivy.lang.builder import Builder
from kivy.properties import BooleanProperty, StringProperty
from redux import AutorunOptions
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu

from ubo_app.colors import DANGER_COLOR, SUCCESS_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.types import CloseApplicationAction, MenuGoBackAction
from ubo_app.store.main import store
from ubo_app.store.services.zigbee import (
    ZigbeeEntity,
    ZigbeeEntityPlatform,
    ZigbeeRefreshDevicesEvent,
    ZigbeeToggleEntityAction,
)
from ubo_app.store.ubo_actions import UboApplicationItem, register_application
from ubo_app.utils.async_ import create_task
from ubo_app.utils.gui import UboPageWidget, UboPromptWidget

# Import sensor_view to ensure register_application is called
from . import sensor_view as _sensor_view_module  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ubo_app.store.main import RootState


class _RemoveDeviceConfirmPage(UboPromptWidget):
    """Confirmation page for device removal."""

    def __init__(self, device_ieee: str, device_name: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.device_ieee = device_ieee
        self.title = 'Remove Device?'
        self.prompt = (
            f'Remove "{device_name}" from the network?\nPress back to cancel'
        )
        self.icon = ''
        self.first_option_label = ''
        self.second_option_label = 'Remove'
        self.second_option_icon = ICON_DELETE
        self.second_option_is_short = False
        self.second_option_background_color = DANGER_COLOR

    def first_option_callback(self) -> None:
        """Not used — first option is hidden."""

    def second_option_callback(self) -> None:
        """Confirm removal."""
        from setup import get_network_manager

        async def _remove() -> None:
            manager = get_network_manager()
            await manager.remove_device(self.device_ieee)
            # Refresh device list
            from setup import _refresh_devices

            await _refresh_devices(ZigbeeRefreshDevicesEvent())

        create_task(_remove())
        # Close confirm page and go back past the removed device's control menu
        store.dispatch(
            CloseApplicationAction(application_instance_id=self.id),
            MenuGoBackAction(),
        )


register_application(
    application=_RemoveDeviceConfirmPage,
    application_id='zigbee:remove-device-confirm',
)


class DeviceControlPage(UboPageWidget):
    """Page for controlling a specific device."""

    device_ieee: str = StringProperty('')
    device_name: str = StringProperty('')
    device_model: str = StringProperty('')
    device_manufacturer: str = StringProperty('')
    is_available: bool = BooleanProperty(True)  # noqa: FBT003

    def __init__(self, device_ieee: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.device_ieee = device_ieee
        self._load_device_info()

    def _load_device_info(self) -> None:
        """Load device information from the network manager."""
        from setup import get_network_manager

        manager = get_network_manager()
        device_info = manager.get_device_by_ieee(self.device_ieee)

        if device_info:
            self.device_name = device_info['name']
            self.device_model = device_info['model'] or 'Unknown'
            self.device_manufacturer = device_info['manufacturer'] or 'Unknown'
            self.is_available = device_info['available']


register_application(
    application=DeviceControlPage,
    application_id='zigbee:device-control',
)


def _get_entity_icon(platform: ZigbeeEntityPlatform) -> str:
    """Get icon based on entity platform."""
    if platform == ZigbeeEntityPlatform.LIGHT:
        return ICON_LIGHT
    if platform == ZigbeeEntityPlatform.SWITCH:
        return ICON_SWITCH
    return ICON_SENSOR


def _get_device_data(
    state: RootState,
    device_ieee: str,
) -> tuple[str, Sequence[ZigbeeEntity], Sequence[ZigbeeEntity]] | None:
    """Extract device data from state for autorun selector."""
    devices = state.zigbee.devices
    if not devices:
        return None
    for device in devices:
        if device.ieee == device_ieee:
            controllable = tuple(e for e in device.entities if e.is_controllable)
            monitorable = tuple(e for e in device.entities if not e.is_controllable)
            device_name = device.custom_name or device.name
            return (device_name, controllable, monitorable)
    return None


def get_device_control_menu(
    device_ieee: str,
) -> Callable[[], HeadedMenu | HeadlessMenu]:
    """Get the device control menu for a specific device."""

    @store.autorun(
        lambda state: _get_device_data(state, device_ieee),
        options=AutorunOptions(default_value=None),
    )
    def _menu(
        data: tuple[str, Sequence[ZigbeeEntity], Sequence[ZigbeeEntity]] | None,
    ) -> HeadedMenu | HeadlessMenu:
        if data is None:
            return HeadedMenu(
                title=f'{ICON_ZIGBEE} Device',
                heading='Loading...',
                sub_heading='Fetching device data',
                items=[],
                placeholder=ICON_LOADING,
            )

        device_name, controllable, monitorable = data

        items: list[ActionItem | UboApplicationItem] = []

        # Add controllable entities (switches, lights)
        for entity in controllable:
            action_label = 'Turn Off' if entity.is_on else 'Turn On'
            bg_color = DANGER_COLOR if entity.is_on else SUCCESS_COLOR

            items.append(
                ActionItem(
                    key=entity.unique_id,
                    label=f'{entity.display_name}: {action_label}',
                    icon=_get_entity_icon(entity.platform),
                    background_color=bg_color,
                    action=lambda uid=entity.unique_id: store.dispatch(
                        ZigbeeToggleEntityAction(
                            device_ieee=device_ieee,
                            entity_unique_id=uid,
                        ),
                    ),
                ),
            )

        # Add sensor view option if there are monitorable entities
        if monitorable:
            from . import sensor_view

            items.append(
                ActionItem(
                    key='sensors',
                    label=f'Sensors ({len(monitorable)})',
                    icon=ICON_SENSOR,
                    action=lambda ieee=device_ieee: sensor_view.get_sensor_menu(ieee),
                ),
            )

        # Device management options
        items.append(
            ActionItem(
                key='rename',
                label='Rename device',
                icon=ICON_RENAME,
                action=lambda: _rename_device(device_ieee, device_name),
            ),
        )

        items.append(
            UboApplicationItem(
                key='remove',
                label='Remove device',
                icon=ICON_DELETE,
                background_color=DANGER_COLOR,
                application_id='zigbee:remove-device-confirm',
                initialization_kwargs={
                    'device_ieee': device_ieee,
                    'device_name': device_name,
                },
            ),
        )

        return HeadlessMenu(
            title=device_name,
            items=items,
        )

    return _menu


def _rename_device(device_ieee: str, current_name: str) -> None:
    """Open rename device dialog."""
    from ubo_app.store.input.types import (
        InputFieldDescription,
        InputFieldType,
        WebUIInputDescription,
    )
    from ubo_app.utils.input import ubo_input

    async def _do_rename() -> None:
        from setup import _refresh_devices, get_network_manager

        descriptions: list[WebUIInputDescription] = [
            WebUIInputDescription(
                fields=[
                    InputFieldDescription(
                        name='name',
                        label='Device Name',
                        type=InputFieldType.TEXT,
                        description='Enter a name for this device',
                        default_value=current_name,
                        required=True,
                    ),
                ],
            ),
        ]

        try:
            _, result = await ubo_input(
                prompt='Rename Device',
                descriptions=descriptions,
            )

            if result and 'name' in result.data:
                name = result.data['name']
                manager = get_network_manager()
                manager.set_device_name(device_ieee, name)
                # Refresh device list
                await _refresh_devices(ZigbeeRefreshDevicesEvent())
        except Exception:  # noqa: BLE001
            logger.debug('Device rename cancelled or failed')

    create_task(_do_rename())


Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('device_control.kv')
    .resolve()
    .as_posix(),
)
