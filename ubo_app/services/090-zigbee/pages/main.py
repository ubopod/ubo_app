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
    ICON_LOADING,
    ICON_REFRESH,
    ICON_ZIGBEE,
)
from ubo_gui.menu.types import (
    ActionItem,
    HeadedMenu,
    HeadlessMenu,
)

from ubo_app.store.main import store
from ubo_app.store.services.zigbee import (
    ZigbeeConnectAction,
    ZigbeeConnectionState,
    ZigbeeCoordinator,
    ZigbeeDetectCoordinatorsAction,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


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
        state.zigbee.connection_state,
        state.zigbee.current_coordinator,
        tuple(
            (d.ieee, d.name, d.custom_name, d.available)
            for d in (state.zigbee.devices or ())
        ),
        state.zigbee.is_pairing,
        state.zigbee.pairing_remaining_seconds,
        state.zigbee.joining_device_name,
    ),
)
def connection_menu(
    data: tuple[
        ZigbeeConnectionState,
        ZigbeeCoordinator | None,
        tuple[tuple[str, str, str | None, bool], ...],
        bool,
        int,
        str | None,
    ],
) -> HeadedMenu | HeadlessMenu:
    """Coordinator setup sub-menu (level 3): connecting/connected state."""
    (
        connection_state,
        current_coordinator,
        device_summaries,
        is_pairing,
        pairing_rem,
        joining_device_name,
    ) = data

    if connection_state == ZigbeeConnectionState.CONNECTED and current_coordinator:
        from . import device_list

        return device_list.build_connected_menu(
            current_coordinator,
            device_summaries,
            is_pairing=is_pairing,
            pairing_remaining=pairing_rem,
            joining_device_name=joining_device_name,
        )

    if connection_state == ZigbeeConnectionState.ERROR:
        return HeadedMenu(
            title=f'{ICON_ZIGBEE} Zigbee',
            heading='Connection Failed',
            sub_heading='Could not connect to coordinator',
            items=[],
        )

    # CONNECTING or DISCONNECTED (transitional state before CONNECTING takes effect)
    return HeadedMenu(
        title=f'{ICON_ZIGBEE} Zigbee',
        heading='Connecting...',
        sub_heading='Setting up Zigbee network',
        items=[],
        placeholder=ICON_LOADING,
    )


def _select_coordinator(
    coord: ZigbeeCoordinator,
) -> Callable[[], HeadedMenu | HeadlessMenu]:
    """Select a coordinator - connect and push to setup sub-menu."""
    store.dispatch(ZigbeeConnectAction(coordinator=coord))
    return connection_menu


@store.autorun(
    lambda state: (
        state.zigbee.coordinators,
        state.zigbee.is_detecting,
        state.zigbee.connection_state,
        state.zigbee.current_coordinator,
    ),
)
def coordinator_menu(
    data: tuple[
        Sequence[ZigbeeCoordinator] | None,
        bool,
        ZigbeeConnectionState,
        ZigbeeCoordinator | None,
    ],
) -> HeadedMenu | HeadlessMenu:
    """Coordinator selection menu (level 2)."""
    coordinators, is_detecting, connection_state, current_coordinator = data

    # Show prominent loading screen while detecting
    if is_detecting or coordinators is None:
        return HeadedMenu(
            title=f'{ICON_ZIGBEE} Zigbee',
            heading='Scanning...',
            sub_heading='Detecting Zigbee coordinators',
            items=[],
            placeholder=ICON_LOADING,
        )

    items: list[ActionItem] = []

    # Add coordinator items
    if coordinators:
        for coord in coordinators:
            name = coord.name or coord.description
            items.append(
                ActionItem(
                    key=coord.port,
                    label=name,
                    icon=_get_coordinator_icon(
                        coord, connection_state, current_coordinator,
                    ),
                    action=lambda c=coord: _select_coordinator(c),
                ),
            )

    # Add action items
    items.append(
        ActionItem(
            key='retry',
            label='Retry Detection',
            icon=ICON_REFRESH,
            action=lambda: store.dispatch(ZigbeeDetectCoordinatorsAction()),
        ),
    )

    items.append(
        ActionItem(
            key='backups',
            label='Manage Backups',
            icon=ICON_BACKUP,
            action=_open_backup_menu,
        ),
    )

    placeholder = 'No coordinators found'

    return HeadlessMenu(
        title='Coordinators',
        items=items,
        placeholder=placeholder,
    )


def _open_backup_menu() -> Callable[[], HeadedMenu | HeadlessMenu]:
    """Open the backup management menu."""
    from . import backup_management

    return backup_management.backup_menu


def _start_detection() -> Callable[[], HeadedMenu | HeadlessMenu]:
    """Start coordinator detection and return the menu."""
    from setup import get_network_manager

    # If already connected, go directly to the device menu
    if get_network_manager().is_running:
        return connection_menu

    # Start fresh detection
    store.dispatch(ZigbeeDetectCoordinatorsAction())
    return coordinator_menu


# Main entry point menu item - directly shows coordinator menu and triggers detection
ZigbeeMainMenu = ActionItem(
    label='Zigbee',
    icon=ICON_ZIGBEE,
    action=_start_detection,
)
