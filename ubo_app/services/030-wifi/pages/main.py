# ruff: noqa: D100
from __future__ import annotations

from typing import TYPE_CHECKING

from constants import WIFI_CONNECTIONS_MENU_ID, get_signal_icon

from ubo_app.logger import logger
from ubo_app.store.core.types import (
    MenuItemData,
    OpenApplicationAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.wifi import (
    ConnectionState,
    WiFiConnection,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


# Icon mapping for connection states
_CONNECTION_STATE_ICONS = {
    ConnectionState.CONNECTED: '󱚽',
    ConnectionState.DISCONNECTED: '󱛅',
    ConnectionState.CONNECTING: '󱛇',
    ConnectionState.UNKNOWN: '󱚵',
}


def _get_connection_icon(connection: WiFiConnection) -> str:
    """Get the appropriate icon for a WiFi connection based on its state."""
    if connection.state == ConnectionState.DISCONNECTED:
        return get_signal_icon(connection.signal_strength)
    return _CONNECTION_STATE_ICONS[connection.state]


def _register_wifi_action_handlers(
    connections: Sequence[WiFiConnection] | None,
) -> None:
    """Register action handlers for WiFi connections."""
    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
        unregister_action,
    )

    # Unregister all existing wifi:open-connection: handlers
    for action_id in get_registered_actions():
        if action_id.startswith('wifi:open-connection:'):
            unregister_action(action_id)

    if connections is None:
        return

    # Register handlers for each connection
    for connection in connections:
        ssid = connection.ssid

        def _make_handler(ssid_val: str) -> Callable[[], None]:
            def _handler() -> None:
                store.dispatch(
                    OpenApplicationAction(
                        application_id='wifi:connection-page',
                        initialization_kwargs={'ssid': ssid_val},
                    ),
                )

            return _handler

        register_action(f'wifi:open-connection:{ssid}', _make_handler(ssid))


@store.autorun(lambda state: state.wifi.connections)
def update_wifi_dynamic_menu(
    connections: Sequence[WiFiConnection] | None,
) -> None:
    """Update the dynamic menu for WiFi connections (dumb UI architecture).

    This autorun dispatches UpdateDynamicMenuAction with serializable MenuItemData.
    """
    # Register action handlers for opening connection pages
    _register_wifi_action_handlers(connections)

    if connections is None:
        items: tuple[MenuItemData | None, ...] = ()
        placeholder = 'Loading...'
    else:
        items = tuple(
            MenuItemData(
                key=f'connection:{connection.ssid}',
                label=connection.ssid,
                icon=_get_connection_icon(connection),
                action_id=f'wifi:open-connection:{connection.ssid}',
            )
            for connection in connections
        )
        placeholder = 'No Wi-Fi connections found' if not connections else ''

    logger.debug(
        '[WiFi Service] Updating dynamic menu: %d connections',
        len(connections) if connections else 0,
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=WIFI_CONNECTIONS_MENU_ID,
            title='Wi-Fi',
            items=items,
            placeholder=placeholder,
        ),
    )
