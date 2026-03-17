# ruff: noqa: D100
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from constants import WIFI_CONNECTIONS_MENU_ID, WIFI_SETTINGS_MENU_ID, get_signal_icon

from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action
from ubo_app.store.core.types import (
    ApplicationStackItem,
    MenuItemData,
    OpenApplicationAction,
    UpdateApplicationKwargsAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.wifi import (
    ConnectionState,
    WiFiConnection,
    WiFiUpdateRequestAction,
)
from ubo_app.utils import IS_RPI
from ubo_app.utils.async_ import create_task

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


def _make_open_handler(ssid: str, state: str) -> Callable[[], None]:
    """Create handler for opening a WiFi connection page."""
    def _handler() -> None:
        store.dispatch(
            OpenApplicationAction(
                application_id='wifi:connection-page',
                initialization_kwargs={'ssid': ssid, 'state': state},
            ),
        )

    return _handler


def _make_connect_handler(ssid: str) -> Callable[[], None]:
    """Create handler for connecting to a WiFi network."""
    def _handler() -> None:
        from wifi_manager import connect_wireless_connection

        create_task(connect_wireless_connection(ssid))
        store.dispatch(WiFiUpdateRequestAction(reset=True))

    return _handler


def _make_disconnect_handler() -> Callable[[], None]:
    """Create handler for disconnecting from a WiFi network."""
    def _handler() -> None:
        from wifi_manager import disconnect_wireless_connection

        create_task(disconnect_wireless_connection())
        store.dispatch(WiFiUpdateRequestAction(reset=True))

    return _handler


def _make_forget_handler(ssid: str) -> Callable[[], None]:
    """Create handler for forgetting a WiFi network."""
    def _handler() -> None:
        from wifi_manager import forget_wireless_connection

        create_task(forget_wireless_connection(ssid))
        store.dispatch(WiFiUpdateRequestAction(reset=True))

    return _handler


_WIFI_ACTION_PREFIXES = (
    'wifi:open-connection:',
    'wifi:connect:',
    'wifi:disconnect:',
    'wifi:forget:',
)


@dataclass
class _WiFiMenuCache:
    """Cache for WiFi menu state to avoid redundant updates."""

    connection_fingerprint: set[tuple[str, str]] = field(default_factory=set)
    menu_items: tuple[MenuItemData | None, ...] = ()
    menu_placeholder: str = ''


_cache = _WiFiMenuCache()


def _connection_fingerprint(
    connections: Sequence[WiFiConnection] | None,
) -> set[tuple[str, str]]:
    """Build a fingerprint set of (ssid, state) for change detection."""
    if connections is None:
        return set()
    return {(c.ssid, c.state.value) for c in connections}


def _register_wifi_action_handlers(
    connections: Sequence[WiFiConnection] | None,
) -> None:
    """Register action handlers for WiFi connections.

    Skips re-registration if the connections haven't meaningfully changed.
    """
    fingerprint = _connection_fingerprint(connections)
    if fingerprint == _cache.connection_fingerprint:
        return
    _cache.connection_fingerprint = fingerprint

    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
        unregister_action,
    )

    for action_id in get_registered_actions():
        if action_id.startswith(_WIFI_ACTION_PREFIXES):
            unregister_action(action_id)

    if connections is None:
        return

    for connection in connections:
        ssid = connection.ssid
        state = connection.state.value
        register_action(f'wifi:open-connection:{ssid}', _make_open_handler(ssid, state))
        register_action(f'wifi:connect:{ssid}', _make_connect_handler(ssid))
        register_action(f'wifi:disconnect:{ssid}', _make_disconnect_handler())
        register_action(f'wifi:forget:{ssid}', _make_forget_handler(ssid))

    logger.debug(
        '[WiFi Service] Re-registered action handlers for %d connections',
        len(connections),
    )


@store.autorun(lambda state: state.wifi.connections)
def update_wifi_dynamic_menu(
    connections: Sequence[WiFiConnection] | None,
) -> None:
    """Update the dynamic menu for WiFi connections (dumb UI architecture).

    This autorun dispatches UpdateDynamicMenuAction with serializable MenuItemData.
    Skips dispatch if menu content hasn't changed.
    """
    # Register action handlers (internally skips if unchanged)
    _register_wifi_action_handlers(connections)

    if not IS_RPI:
        items: tuple[MenuItemData | None, ...] = ()
        placeholder = 'D-Bus unavailable on this platform'
    elif connections is None:
        items = ()
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

    if items == _cache.menu_items and placeholder == _cache.menu_placeholder:
        return

    _cache.menu_items = items
    _cache.menu_placeholder = placeholder

    logger.debug(
        '[WiFi Service] Updating dynamic menu: %d connections',
        len(connections) if connections else 0,
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=WIFI_CONNECTIONS_MENU_ID,
            title='Wi-Fi Connections',
            items=items,
            placeholder=placeholder,
        ),
    )


# --- Intermediate "WiFi Settings" menu (Add / Select) ---

store.dispatch(
    UpdateDynamicMenuAction(
        menu_id=WIFI_SETTINGS_MENU_ID,
        title='WiFi Settings',
        items=(
            MenuItemData(
                key='add',
                label='Add',
                icon='󱛃',
                action_id='wifi:add-connection',
            ),
            MenuItemData(
                key='wifi:connections',
                label='Select',
                icon='󱖫',
                action_id='wifi:select-connections',
            ),
        ),
    ),
)


def _add_connection() -> None:
    from pages.create_wireless_connection import input_wifi_connection

    create_task(input_wifi_connection())


register_action('wifi:add-connection', _add_connection)


def _select_connections() -> bool:
    store.dispatch(WiFiUpdateRequestAction())
    return True


register_action('wifi:select-connections', _select_connections)


# --- Application button handlers for wifi:connection-page ---
# These handle physical button presses (RPi) on the WiFi connection page.
# L1 (index 0) = connect/disconnect, L2 (index 1) = forget/delete

def _connection_page_first_button() -> None:
    """Handle connect/disconnect button on the WiFi connection page."""
    from ubo_app.store.core.action_registry import execute_action

    @store.with_state(lambda state: state.main.stack)
    def _handle(stack: tuple) -> None:
        top = stack[-1] if stack else None
        if not isinstance(top, ApplicationStackItem):
            return
        ssid = top.initialization_kwargs.get('ssid', '')
        current_state = top.initialization_kwargs.get('state', '')
        if current_state == ConnectionState.CONNECTED.value:
            execute_action(f'wifi:disconnect:{ssid}')
            new_state = ConnectionState.DISCONNECTED.value
        else:
            execute_action(f'wifi:connect:{ssid}')
            new_state = ConnectionState.CONNECTING.value

        store.dispatch(
            UpdateApplicationKwargsAction(
                application_id='wifi:connection-page',
                kwargs={'state': new_state},
            ),
        )

    _handle()


def _connection_page_second_button() -> None:
    """Handle forget/delete button on the WiFi connection page."""
    from ubo_app.store.core.action_registry import execute_action
    from ubo_app.store.core.types import CloseApplicationAction

    @store.with_state(lambda state: state.main.stack)
    def _handle(stack: tuple) -> None:
        top = stack[-1] if stack else None
        if not isinstance(top, ApplicationStackItem):
            return
        ssid = top.initialization_kwargs.get('ssid', '')
        execute_action(f'wifi:forget:{ssid}')
        store.dispatch(CloseApplicationAction(application_instance_id=top.id))

    _handle()


register_action('app-button:wifi:connection-page:1', _connection_page_first_button)
register_action('app-button:wifi:connection-page:2', _connection_page_second_button)


# --- Reactive state updates for the WiFi connection page ---


@store.autorun(lambda state: state.wifi.connections)
def _update_connection_page_state(
    connections: Sequence[WiFiConnection] | None,
) -> None:
    """Reactively update the WiFi connection page when connection state changes."""
    if connections is None:
        return

    connection_states = {c.ssid: c.state.value for c in connections}

    @store.with_state(lambda state: state.main.stack)
    def _check_stack(stack: tuple) -> None:
        top = stack[-1] if stack else None
        if not isinstance(top, ApplicationStackItem):
            return
        if top.application_id != 'wifi:connection-page':
            return
        ssid = str(top.initialization_kwargs.get('ssid', ''))
        current_state = str(top.initialization_kwargs.get('state', ''))
        new_state = connection_states.get(ssid)
        if new_state is not None and new_state != current_state:
            store.dispatch(
                UpdateApplicationKwargsAction(
                    application_id='wifi:connection-page',
                    kwargs={'state': new_state},
                ),
            )

    _check_stack()
