# ruff: noqa: D100, D103
"""Device list page for the Zigbee service.

Shows paired devices when connected to a coordinator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Import device_control to ensure register_application is called
from . import device_control as _device_control_module  # noqa: F401

from constants import (
    ICON_BACKUP,
    ICON_DELETE,
    ICON_DEVICE_AVAILABLE,
    ICON_DEVICE_UNAVAILABLE,
    ICON_PAIRING,
    ICON_RENAME,
    ICON_RESET,
    ICON_ZIGBEE,
)
from ubo_gui.menu.types import ActionItem, HeadedMenu, HeadlessMenu

from ubo_app.colors import DANGER_COLOR
from ubo_app.store.core.types import CloseApplicationAction
from ubo_app.store.main import store
from ubo_app.store.services.zigbee import (
    ZigbeeCoordinator,
    ZigbeeCreateBackupAction,
    ZigbeeDevice,
    ZigbeeDisconnectAction,
    ZigbeeResetNetworkAction,
    ZigbeeStartPairingAction,
    ZigbeeStopPairingAction,
)
from ubo_app.store.ubo_actions import UboApplicationItem, register_application
from ubo_app.utils.gui import UboPromptWidget

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class _ResetNetworkConfirmPage(UboPromptWidget):
    """Confirmation page for network reset."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.title = 'Reset Network?'
        self.prompt = 'This will remove ALL paired devices and reset the network.'
        self.icon = ICON_RESET
        self.first_option_label = 'Reset'
        self.first_option_icon = ICON_RESET
        self.first_option_is_short = False
        self.first_option_background_color = DANGER_COLOR
        self.second_option_label = 'Cancel'
        self.second_option_icon = '󰜺'
        self.second_option_is_short = False

    def first_option_callback(self) -> None:
        """Confirm reset."""
        store.dispatch(
            ZigbeeResetNetworkAction(),
            CloseApplicationAction(application_instance_id=self.id),
        )

    def second_option_callback(self) -> None:
        """Cancel reset."""
        store.dispatch(CloseApplicationAction(application_instance_id=self.id))


register_application(
    application=_ResetNetworkConfirmPage,
    application_id='zigbee:reset-network-confirm',
)


def _get_device_icon(device: ZigbeeDevice) -> str:
    """Get icon based on device availability."""
    return ICON_DEVICE_AVAILABLE if device.available else ICON_DEVICE_UNAVAILABLE


def _pairing_duration_menu() -> HeadlessMenu:
    """Sub-menu for selecting pairing duration."""
    return HeadlessMenu(
        title='Pair Device',
        items=[
            ActionItem(
                key='pair-30',
                label='30 seconds',
                icon=ICON_PAIRING,
                action=lambda: store.dispatch(ZigbeeStartPairingAction(duration=30)),
            ),
            ActionItem(
                key='pair-60',
                label='60 seconds',
                icon=ICON_PAIRING,
                action=lambda: store.dispatch(ZigbeeStartPairingAction(duration=60)),
            ),
        ],
    )


def build_connected_menu(
    current_coordinator: ZigbeeCoordinator | None,
    devices: Sequence[ZigbeeDevice] | None,
    is_pairing: bool,
    pairing_remaining: int,
) -> HeadlessMenu | HeadedMenu:
    """Generate the main menu when connected to a coordinator."""
    if current_coordinator:
        title = current_coordinator.name or current_coordinator.description
    else:
        title = f'{ICON_ZIGBEE} Zigbee'

    # Show pairing screen when actively pairing
    if is_pairing:
        return HeadedMenu(
            title=title,
            heading=f'Pairing... ({pairing_remaining}s)',
            sub_heading='Waiting for device...',
            items=[
                ActionItem(
                    key='stop-pairing',
                    label='Stop Pairing',
                    icon='󰜺',
                    action=lambda: store.dispatch(ZigbeeStopPairingAction()),
                ),
            ],
            placeholder='',
        )

    items: list[ActionItem | UboApplicationItem] = []

    # List paired devices directly - each opens a device control menu
    if devices:
        from . import device_control

        for device in devices:
            display_name = device.custom_name or device.name
            items.append(
                ActionItem(
                    key=device.ieee,
                    label=display_name,
                    icon=_get_device_icon(device),
                    action=device_control.get_device_control_menu(device.ieee),
                )
            )

    # Pair device (opens duration sub-menu)
    items.append(
        ActionItem(
            key='pair',
            label='Pair Device',
            icon=ICON_PAIRING,
            action=_pairing_duration_menu,
        )
    )

    # Coordinator management
    items.append(
        ActionItem(
            key='rename-coordinator',
            label='Rename coordinator',
            icon=ICON_RENAME,
            action=_rename_coordinator,
        )
    )

    # Backup
    items.append(
        ActionItem(
            key='update-backup',
            label='Update backup',
            icon=ICON_BACKUP,
            action=lambda: store.dispatch(ZigbeeCreateBackupAction()),
        )
    )

    # Network reset (with confirmation)
    items.append(
        UboApplicationItem(
            key='reset-network',
            label='Reset network',
            icon=ICON_RESET,
            application_id='zigbee:reset-network-confirm',
        )
    )

    return HeadlessMenu(
        title=title,
        items=items,
        placeholder='No devices paired',
    )


def _rename_coordinator() -> None:
    """Open rename coordinator dialog."""
    from ubo_app.store.input.types import (
        InputDescription,
        InputFieldDescription,
        InputFieldType,
        WebUIInputDescription,
    )
    from ubo_app.utils.async_ import create_task
    from ubo_app.utils.input import ubo_input

    async def _do_rename() -> None:
        from setup import get_network_manager

        coordinator = store.snapshot.zigbee.current_coordinator
        if not coordinator:
            return

        descriptions: list[InputDescription] = [
            WebUIInputDescription(
                fields=[
                    InputFieldDescription(
                        name='name',
                        label='Coordinator Name',
                        type=InputFieldType.TEXT,
                        description='Enter a name for this coordinator',
                        default_value=coordinator.name or '',
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
                manager = get_network_manager()
                manager.set_coordinator_name(coordinator.port, name)

                # Refresh coordinators to update name
                from ubo_app.store.services.zigbee import (
                    ZigbeeCoordinator,
                    ZigbeeSetConnectionStateAction,
                    ZigbeeConnectionState,
                )

                # Update current coordinator with new name
                updated = ZigbeeCoordinator(
                    port=coordinator.port,
                    description=coordinator.description,
                    radio_type=coordinator.radio_type,
                    baudrate=coordinator.baudrate,
                    name=name,
                    has_network=coordinator.has_network,
                )
                store.dispatch(
                    ZigbeeSetConnectionStateAction(
                        state=ZigbeeConnectionState.CONNECTED,
                        coordinator=updated,
                    )
                )
        except Exception:
            pass  # User cancelled

    create_task(_do_rename())
