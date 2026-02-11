"""Device list page for the Zigbee service.

Shows paired devices when connected to a coordinator.
"""

from __future__ import annotations

import functools

from constants import (
    ICON_BACKUP,
    ICON_DEVICE_AVAILABLE,
    ICON_DEVICE_UNAVAILABLE,
    ICON_LOADING,
    ICON_PAIRING,
    ICON_RENAME,
    ICON_RESET,
    ICON_SUCCESS,
    ICON_ZIGBEE,
)
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu

from ubo_app.colors import DANGER_COLOR, SUCCESS_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.types import CloseApplicationAction, MenuGoBackAction
from ubo_app.store.main import store
from ubo_app.store.services.zigbee import (
    ZigbeeCoordinator,
    ZigbeeCreateBackupAction,
    ZigbeeResetNetworkAction,
    ZigbeeSetJoiningDeviceAction,
    ZigbeeStartPairingAction,
    ZigbeeStopPairingAction,
)
from ubo_app.store.ubo_actions import UboApplicationItem, register_application
from ubo_app.utils.gui import UboPromptWidget

# Import device_control to ensure register_application is called
from . import device_control as _device_control_module  # noqa: F401


class _ResetNetworkConfirmPage(UboPromptWidget):
    """Confirmation page for network reset."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.title = 'Reset Network?'
        self.prompt = (
            'This will remove ALL paired devices and reset the network.\n'
            'Press back to cancel'
        )
        self.icon = ICON_RESET
        self.first_option_label = ''
        self.second_option_label = 'Reset'
        self.second_option_icon = ICON_RESET
        self.second_option_is_short = False
        self.second_option_background_color = DANGER_COLOR

    def first_option_callback(self) -> None:
        """Not used — first option is hidden."""

    def second_option_callback(self) -> None:
        """Confirm reset."""
        store.dispatch(
            ZigbeeResetNetworkAction(),
            CloseApplicationAction(application_instance_id=self.id),
        )


register_application(
    application=_ResetNetworkConfirmPage,
    application_id='zigbee:reset-network-confirm',
)


def _get_device_icon(*, available: bool) -> str:
    """Get icon based on device availability."""
    return ICON_DEVICE_AVAILABLE if available else ICON_DEVICE_UNAVAILABLE


def _pairing_duration_menu() -> HeadlessMenu:
    """Sub-menu for selecting pairing duration."""

    def _start_pairing(duration: int) -> None:
        store.dispatch(
            ZigbeeStartPairingAction(duration=duration),
            MenuGoBackAction(),
        )

    return HeadlessMenu(
        title='Pair Device',
        items=[
            ActionItem(
                key='pair-30',
                label='30 seconds',
                icon=ICON_PAIRING,
                action=lambda: _start_pairing(30),
            ),
            ActionItem(
                key='pair-60',
                label='60 seconds',
                icon=ICON_PAIRING,
                action=lambda: _start_pairing(60),
            ),
        ],
    )


def build_connected_menu(
    current_coordinator: ZigbeeCoordinator | None,
    device_summaries: tuple[tuple[str, str, str | None, bool], ...],
    *,
    is_pairing: bool,
    pairing_remaining: int,
    joining_device_name: str | None = None,
) -> HeadlessMenu | HeadedMenu:
    """Generate the main menu when connected to a coordinator.

    Always returns HeadedMenu so the framework can update heading/sub_heading
    in-place via Kivy StringProperty bindings instead of full page transitions.
    """
    if current_coordinator:
        title = current_coordinator.name or current_coordinator.description
    else:
        title = f'{ICON_ZIGBEE} Zigbee'

    # Device successfully paired — show success with Done button
    if joining_device_name and not is_pairing:
        return HeadedMenu(
            title=title,
            heading=f'{joining_device_name} Added',
            sub_heading='Device is ready',
            items=[
                ActionItem(
                    key='done',
                    label='Done',
                    icon=ICON_SUCCESS,
                    background_color=SUCCESS_COLOR,
                    action=lambda: store.dispatch(
                        ZigbeeSetJoiningDeviceAction(device_name=None),
                    ),
                ),
            ],
        )

    # Device detected/initializing during active pairing
    if joining_device_name:
        return HeadedMenu(
            title=title,
            heading=f'Setting up {joining_device_name}...',
            sub_heading='Initializing device',
            items=[],
            placeholder=ICON_LOADING,
        )

    # Pairing countdown with cancel option
    if is_pairing:
        return HeadedMenu(
            title=title,
            heading=f'Pairing... ({pairing_remaining}s)',
            sub_heading='Listening for devices...',
            items=[
                ActionItem(
                    key='cancel-pairing',
                    label='Cancel',
                    icon=ICON_RESET,
                    action=lambda: store.dispatch(
                        ZigbeeStopPairingAction(),
                        ZigbeeSetJoiningDeviceAction(device_name=None),
                    ),
                ),
            ],
        )

    items: list[ActionItem | UboApplicationItem] = []

    # List paired devices directly - each opens a device control menu
    if device_summaries:
        from . import device_control

        for ieee, name, custom_name, available in device_summaries:
            display_name = custom_name or name
            items.append(
                ActionItem(
                    key=ieee,
                    label=display_name,
                    icon=_get_device_icon(available=available),
                    action=functools.partial(
                        device_control.get_device_control_menu, ieee,
                    ),
                ),
            )

    # Pair device (opens duration sub-menu)
    items.append(
        ActionItem(
            key='pair',
            label='Pair Device',
            icon=ICON_PAIRING,
            action=_pairing_duration_menu,
        ),
    )

    # Coordinator management
    items.append(
        ActionItem(
            key='rename-coordinator',
            label='Rename coordinator',
            icon=ICON_RENAME,
            action=_rename_coordinator,
        ),
    )

    # Backup
    items.append(
        ActionItem(
            key='update-backup',
            label='Update backup',
            icon=ICON_BACKUP,
            action=lambda: store.dispatch(ZigbeeCreateBackupAction()),
        ),
    )

    # Network reset (with confirmation)
    items.append(
        UboApplicationItem(
            key='reset-network',
            label='Reset network',
            icon=ICON_RESET,
            background_color=DANGER_COLOR,
            application_id='zigbee:reset-network-confirm',
        ),
    )

    return HeadlessMenu(
        title=title,
        items=items,
        placeholder='No devices paired',
    )


def _rename_coordinator() -> None:
    """Open rename coordinator dialog."""
    from ubo_app.store.input.types import (
        InputFieldDescription,
        InputFieldType,
        WebUIInputDescription,
    )
    from ubo_app.utils.async_ import create_task
    from ubo_app.utils.input import ubo_input

    async def _do_rename() -> None:
        from setup import get_network_manager

        manager = get_network_manager()
        coord = manager.coordinator
        if not coord:
            return

        current_name = manager.get_coordinator_name(coord.port) or ''

        descriptions: list[WebUIInputDescription] = [
            WebUIInputDescription(
                fields=[
                    InputFieldDescription(
                        name='name',
                        label='Coordinator Name',
                        type=InputFieldType.TEXT,
                        description='Enter a name for this coordinator',
                        default_value=current_name,
                        required=True,
                    ),
                ],
            ),
        ]

        try:
            _, result = await ubo_input(
                prompt='Rename Coordinator',
                descriptions=descriptions,
            )

            if result and 'name' in result.data:
                name = result.data['name']
                manager.set_coordinator_name(coord.port, name)

                # Refresh coordinators to update name
                from ubo_app.store.services.zigbee import (
                    ZigbeeConnectionState,
                    ZigbeeCoordinator,
                    ZigbeeSetConnectionStateAction,
                )

                # Update current coordinator with new name
                updated = ZigbeeCoordinator(
                    port=coord.port,
                    description=coord.description,
                    radio_type=coord.radio_type.name,
                    baudrate=coord.baudrate,
                    name=name,
                    has_network=manager.has_existing_network(coord),
                )
                store.dispatch(
                    ZigbeeSetConnectionStateAction(
                        state=ZigbeeConnectionState.CONNECTED,
                        coordinator=updated,
                    ),
                )
        except Exception:  # noqa: BLE001
            logger.debug('Coordinator rename cancelled or failed')

    create_task(_do_rename())
