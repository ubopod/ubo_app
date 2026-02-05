# ruff: noqa: D100, D103
"""Main coordinator selection page for the Zigbee service.

This is the entry point when navigating to Zigbee in settings.
It shows available coordinators and allows connection management.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from constants import (
    ICON_BACKUP,
    ICON_COORDINATOR_CONNECTED,
    ICON_COORDINATOR_NEW,
    ICON_COORDINATOR_SAVED,
    ICON_REFRESH,
    ICON_ZIGBEE,
)
from ubo_gui.menu.types import (
    ActionItem,
    HeadlessMenu,
    SubMenuItem,
)

from ubo_app.logger import logger
from ubo_app.store.core.types import CloseApplicationAction
from ubo_app.store.main import store
from ubo_app.store.services.zigbee import (
    ZigbeeConnectAction,
    ZigbeeConnectionState,
    ZigbeeCoordinator,
    ZigbeeDetectCoordinatorsAction,
)
from ubo_app.store.ubo_actions import UboApplicationItem, register_application
from ubo_app.utils.gui import UboPromptWidget

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class _CoordinatorPage(UboPromptWidget):
    """Page for coordinator connection actions."""

    def __init__(
        self,
        coordinator: ZigbeeCoordinator,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.coordinator = coordinator

        logger.info(
            'CoordinatorPage opened',
            extra={
                'port': coordinator.port,
                'description': coordinator.description,
                'radio_type': coordinator.radio_type,
            },
        )

        name = self.coordinator.name or self.coordinator.description
        self.title = name
        self.prompt = f'{self.coordinator.radio_type}\n{self.coordinator.port}'

        if self.coordinator.has_network:
            self.icon = ICON_COORDINATOR_SAVED
            self.first_option_label = 'Connect'
            self.first_option_icon = '󰖩'
        else:
            self.icon = ICON_COORDINATOR_NEW
            self.first_option_label = 'Setup'
            self.first_option_icon = '󰐕'

        self.first_option_is_short = False
        self.second_option_label = 'Cancel'
        self.second_option_icon = '󰜺'
        self.second_option_is_short = False

    def first_option_callback(self) -> None:
        """Connect to this coordinator."""
        store.dispatch(
            ZigbeeConnectAction(coordinator=self.coordinator),
            CloseApplicationAction(application_instance_id=self.id),
        )

    def second_option_callback(self) -> None:
        """Cancel and go back."""
        store.dispatch(CloseApplicationAction(application_instance_id=self.id))


register_application(
    application=_CoordinatorPage,
    application_id='zigbee:coordinator-page',
)


def _get_coordinator_icon(
    coordinator: ZigbeeCoordinator,
    connection_state: ZigbeeConnectionState,
    current_coordinator: ZigbeeCoordinator | None,
) -> str:
    """Get icon based on coordinator state."""
    # Check if this is the connected coordinator
    if (
        current_coordinator
        and current_coordinator.port == coordinator.port
        and connection_state == ZigbeeConnectionState.CONNECTED
    ):
        return ICON_COORDINATOR_CONNECTED

    # Has existing network (saved)
    if coordinator.has_network:
        return ICON_COORDINATOR_SAVED

    # New/unknown
    return ICON_COORDINATOR_NEW


@store.autorun(
    lambda state: (
        state.zigbee.coordinators,
        state.zigbee.is_detecting,
        state.zigbee.connection_state,
        state.zigbee.current_coordinator,
    )
)
def coordinator_menu(
    data: tuple[
        Sequence[ZigbeeCoordinator] | None,
        bool,
        ZigbeeConnectionState,
        ZigbeeCoordinator | None,
    ],
) -> HeadlessMenu:
    """Generate the coordinator selection menu."""
    coordinators, is_detecting, connection_state, current_coordinator = data

    # If connected, show the connected menu instead
    if connection_state == ZigbeeConnectionState.CONNECTED and current_coordinator:
        from . import device_list

        return device_list.connected_menu(current_coordinator)

    items: list[ActionItem | UboApplicationItem] = []

    # Add coordinator items
    if coordinators:
        for coord in coordinators:
            name = coord.name or coord.description
            items.append(
                UboApplicationItem(
                    key=coord.port,
                    label=name,
                    icon=_get_coordinator_icon(coord, connection_state, current_coordinator),
                    application_id='zigbee:coordinator-page',
                    initialization_kwargs={'coordinator': coord},
                )
            )

    # Add action items
    items.append(
        ActionItem(
            key='retry',
            label='Retry Detection',
            icon=ICON_REFRESH,
            action=lambda: store.dispatch(ZigbeeDetectCoordinatorsAction()),
        )
    )

    items.append(
        ActionItem(
            key='backups',
            label='Manage Backups',
            icon=ICON_BACKUP,
            action=_open_backup_menu,
        )
    )

    placeholder = 'Detecting...' if is_detecting else 'No coordinators found'
    if coordinators is None:
        placeholder = 'Loading...'

    return HeadlessMenu(
        title='Zigbee Coordinators',
        items=items,
        placeholder=placeholder,
    )


def _open_backup_menu() -> Callable[[], HeadlessMenu]:
    """Open the backup management menu."""
    from . import backup_management

    return backup_management.backup_menu


def _start_detection() -> Callable[[], HeadlessMenu]:
    """Start coordinator detection and return the menu."""
    store.dispatch(ZigbeeDetectCoordinatorsAction())
    return coordinator_menu


# Main entry point menu item
ZigbeeMainMenu = SubMenuItem(
    label='Zigbee',
    icon=ICON_ZIGBEE,
    sub_menu=HeadlessMenu(
        title='Zigbee',
        items=[
            ActionItem(
                label='Coordinators',
                icon=ICON_ZIGBEE,
                action=_start_detection,
            ),
        ],
    ),
)
