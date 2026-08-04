# ruff: noqa: D100
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from constants import (
    WIFI_CONNECTIONS_MENU_ID,
    WIFI_SETTINGS_MENU_ID,
    WIFI_STATE_ICON_ID,
    WIFI_STATE_ICON_PRIORITY,
    get_signal_icon,
)

from ubo_app.colors import SUCCESS_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action
from ubo_app.store.core.types import (
    MenuItemData,
    OpenRenderAction,
    PromptStackItem,
    StackPopAction,
    StackPopItemAction,
    StackPushPromptAction,
    UpdateDynamicMenuAction,
    UpdatePromptAction,
)
from ubo_app.store.core.types.stack_items import RenderStackItem, StackItemType
from ubo_app.store.input.types import InputMethod
from ubo_app.store.main import store
from ubo_app.store.services.ethernet import NetState
from ubo_app.store.services.wifi import (
    ConnectionState,
    WiFiConnection,
    WiFiStartHotspotAction,
    WiFiStopHotspotAction,
    WiFiUpdateRequestAction,
)
from ubo_app.store.status_icons.types import StatusIconsRegisterAction
from ubo_app.utils import IS_RPI
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ubo_app.store.services.ip import IpNetworkInterface


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


def _build_prompt_items(
    ssid: str,
    state: str,
) -> tuple[MenuItemData, ...]:
    """Build prompt action items based on WiFi connection state."""
    if state == ConnectionState.CONNECTED.value:
        first = MenuItemData(
            key='connect-disconnect',
            label='Disconnect',
            icon='󰖪',
            action_id=f'wifi:disconnect:{ssid}',
        )
    elif state == ConnectionState.CONNECTING.value:
        first = MenuItemData(
            key='connect-disconnect',
            label='Connecting...',
            icon='',
            background_color='black',
        )
    elif state == ConnectionState.DISCONNECTED.value:
        first = MenuItemData(
            key='connect-disconnect',
            label='Connect',
            icon='󰖩',
            action_id=f'wifi:connect:{ssid}',
        )
    else:
        first = MenuItemData(
            key='connect-disconnect',
            label='',
            icon='',
            background_color='black',
        )
    return (
        first,
        MenuItemData(
            key='forget',
            label='Delete',
            icon='󰆴',
            action_id=f'wifi:forget:{ssid}',
        ),
    )


def _get_prompt_icon(state: str) -> str:
    """Get the prompt icon based on WiFi connection state."""
    if state == ConnectionState.CONNECTED.value:
        return '󰖩'
    if state == ConnectionState.DISCONNECTED.value:
        return '󰖪'
    return ''


def _make_open_handler(ssid: str, state: str) -> Callable[[], None]:
    """Create handler for opening a WiFi connection page."""
    def _handler() -> None:
        store.dispatch(
            StackPushPromptAction(
                prompt=f'SSID: {ssid}',
                icon=_get_prompt_icon(state),
                items=_build_prompt_items(ssid, state),
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

        store.dispatch(StackPopAction())
        create_task(forget_wireless_connection(ssid))
        store.dispatch(WiFiUpdateRequestAction())

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
            title='Wi-Fi',
            items=items,
            placeholder=placeholder,
        ),
    )


# --- Intermediate "WiFi Settings" menu (Add / Select / Hotspot) ---


@store.autorun(lambda state: state.wifi.is_hotspot_running)
def _update_wifi_settings_menu(is_hotspot_running: bool) -> None:  # noqa: FBT001
    """Render the WiFi settings menu, reflecting the live hotspot state."""
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
                MenuItemData(
                    key='hotspot',
                    label='Hotspot',
                    icon='󰱒' if is_hotspot_running else '󰄱',
                    action_id='wifi:toggle-hotspot',
                ),
            ),
        ),
    )


def _add_connection() -> None:
    from pages.create_wireless_connection import input_wifi_connection

    create_task(input_wifi_connection())


def _add_connection_via_camera() -> None:
    """Run the same flow, forced to the camera/QR-code input method.

    Backs the "WiFi Setup via Camera" voice shortcut, which needs the flow
    (not just its final "creating" status) to actually run.
    """
    from pages.create_wireless_connection import input_wifi_connection

    create_task(input_wifi_connection(input_methods=(InputMethod.CAMERA,)))


def _add_connection_via_web() -> None:
    """Run the same flow, forced to the web-dashboard input method.

    Backs the "WiFi Setup via Web" voice shortcut.
    """
    from pages.create_wireless_connection import input_wifi_connection

    create_task(input_wifi_connection(input_methods=(InputMethod.WEB_DASHBOARD,)))


register_action('wifi:add-connection', _add_connection)
register_action('wifi:add-connection:camera', _add_connection_via_camera)
register_action('wifi:add-connection:web', _add_connection_via_web)


@store.with_state(lambda state: state.wifi.is_hotspot_running)
def _is_hotspot_running(is_hotspot_running: bool) -> bool:  # noqa: FBT001
    return is_hotspot_running


async def _wait_for_hotspot(*, target: bool) -> None:
    """Poll until the hotspot reaches the desired running state (~15s cap)."""
    for _ in range(30):
        if _is_hotspot_running() == target:
            return
        await asyncio.sleep(0.5)


_SWITCHING_STREAM_ID = 'wifi:hotspot-switching'


def _switching_status(text: str) -> OpenRenderAction:
    return OpenRenderAction(
        kind='status',
        title='Hotspot',
        props={
            'icon': '󰖩',
            'text': text,
            'icon_size': 32,
            'text_font_size': 16,
        },
        stream_id=_SWITCHING_STREAM_ID,
    )


def _pop_switching_render() -> None:
    """Pop the "Switching…" status render by id (never the notification on top)."""

    @store.with_state(lambda state: state.main.stack)
    def _pop(stack: tuple[StackItemType, ...]) -> None:
        item = next(
            (
                item
                for item in stack
                if isinstance(item, RenderStackItem)
                and item.stream_id == _SWITCHING_STREAM_ID
            ),
            None,
        )
        if item is not None:
            store.dispatch(StackPopItemAction(item_id=item.id))

    _pop()


async def _switch_to_ap(mode: str) -> None:
    """Switch to AP mode in ``mode`` (share|captive), showing progress until up."""
    store.dispatch(
        _switching_status('Switching to hotspot…'),
        WiFiStartHotspotAction(mode=mode),
    )
    await _wait_for_hotspot(target=True)
    _pop_switching_render()


async def _switch_to_managed() -> None:
    """Switch to managed WiFi: stop the hotspot, let NM autoconnect, then refresh."""
    store.dispatch(
        _switching_status('Switching to WiFi…'),
        WiFiStopHotspotAction(),
    )
    await _wait_for_hotspot(target=False)
    store.dispatch(WiFiUpdateRequestAction(reset=True))
    _pop_switching_render()


# Holds the hotspot mode chosen before the disconnect warning is confirmed, so
# it can be threaded through the warning prompt's single confirm action.
_pending_hotspot_mode: list[str] = []


@store.with_state(
    # Guarded: the ip service may not be loaded (e.g. in focused flow tests),
    # in which case no Ethernet uplink can be confirmed.
    lambda state: (state.ip.is_connected, state.ip.interfaces)
    if hasattr(state, 'ip')
    else (None, ()),
)
def _ethernet_can_share_internet(
    data: tuple[bool | None, Sequence[IpNetworkInterface]],
) -> bool:
    """Report whether an Ethernet uplink with a live internet route exists.

    Sharing only makes sense over a non-WiFi uplink (the hotspot takes over
    wlan0), so the Share/Data-entry choice is offered only when Ethernet is up
    *and* the device actually reaches the internet. ``is_connected`` is a real
    reachability ping; the interface check matches eth*/en* (excluding wlan0,
    lo, docker0, tailscale0, …).
    """
    is_connected, interfaces = data
    if not is_connected:
        return False
    return any(
        interface.ip_addresses and interface.name.startswith(('eth', 'en'))
        for interface in interfaces
    )


def _prompt_mode_chooser() -> None:
    """Ask whether the hotspot is for sharing internet or for data entry."""
    store.dispatch(
        StackPushPromptAction(
            prompt='Start WiFi hotspot?',
            icon='󰖩',
            items=(
                MenuItemData(
                    key='share',
                    label='Share Internet',
                    icon='󰖩',
                    action_id='wifi:hotspot-share',
                ),
                MenuItemData(
                    key='data-entry',
                    label='Data Entry',
                    icon='󰌌',
                    action_id='wifi:hotspot-captive',
                ),
            ),
        ),
    )


def _prompt_switch_warning() -> None:
    """Warn that switching to the hotspot drops the current WiFi connection."""
    store.dispatch(
        StackPushPromptAction(
            prompt='Switch to hotspot?\nThis disconnects WiFi.',
            icon='󰖩',
            items=(
                MenuItemData(
                    key='confirm',
                    label='Continue',
                    icon='󰄬',
                    action_id='wifi:hotspot-confirm',
                ),
                MenuItemData(
                    key='cancel',
                    label='Cancel',
                    icon='󰜺',
                    action_id='wifi:hotspot-cancel',
                ),
            ),
        ),
    )


async def _begin_hotspot_toggle() -> None:
    """Drive the toggle-on journey from the live connectivity.

    - Ethernet-with-internet → ask the purpose (share vs data entry) first.
    - Active WiFi → always warn that switching disconnects WiFi.
    - Neither → just bring the hotspot up (data-entry/captive).
    """
    from wifi_manager import get_active_connection_ssid

    if _ethernet_can_share_internet():
        _prompt_mode_chooser()
        return

    ssid = await get_active_connection_ssid()
    if ssid is not None:
        _pending_hotspot_mode[:] = ['captive']
        _prompt_switch_warning()
        return

    await _switch_to_ap('captive')


async def _continue_after_mode(mode: str) -> None:
    """After the purpose is chosen, warn if WiFi is connected, else start."""
    from wifi_manager import get_active_connection_ssid

    ssid = await get_active_connection_ssid()
    store.dispatch(StackPopAction())  # pop the mode chooser
    if ssid is not None:
        _pending_hotspot_mode[:] = [mode]
        _prompt_switch_warning()
    else:
        await _switch_to_ap(mode)


def _confirm_switch() -> None:
    """Confirm the disconnect warning and bring the hotspot up."""
    mode = _pending_hotspot_mode[0] if _pending_hotspot_mode else 'captive'
    store.dispatch(StackPopAction())  # pop the warning
    create_task(_switch_to_ap(mode))


def _cancel_switch() -> None:
    """Dismiss the disconnect warning without switching (same as BACK)."""
    store.dispatch(StackPopAction())  # pop the warning, stay on WiFi


# Action handlers must return None (a non-None result pushes an empty submenu
# frame), so these wrap create_task instead of returning the Task.
def _choose_share() -> None:
    create_task(_continue_after_mode('share'))


def _choose_captive() -> None:
    create_task(_continue_after_mode('captive'))


def _toggle_hotspot() -> None:
    if _is_hotspot_running():
        create_task(_switch_to_managed())
    else:
        create_task(_begin_hotspot_toggle())


register_action('wifi:toggle-hotspot', _toggle_hotspot)
register_action('wifi:hotspot-share', _choose_share)
register_action('wifi:hotspot-captive', _choose_captive)
register_action('wifi:hotspot-confirm', _confirm_switch)
register_action('wifi:hotspot-cancel', _cancel_switch)


@store.autorun(
    lambda state: (
        state.wifi.is_hotspot_running,
        state.wifi.state,
        state.wifi.current_connection,
    ),
)
def _update_wifi_status_icon(
    data: tuple[bool, NetState, WiFiConnection | None],
) -> None:
    """Register the status-bar WiFi icon; full + green while in hotspot (AP) mode.

    Lives here (not the reducer) so it can read the hotspot flag from the
    cross-slice web_ui state.
    """
    is_hotspot_running, net_state, current_connection = data
    if is_hotspot_running:
        icon = f'[color={SUCCESS_COLOR}]󰤨[/color]'
    elif net_state == NetState.CONNECTED:
        icon = get_signal_icon(
            current_connection.signal_strength if current_connection else 0,
        )
    else:
        icon = {
            NetState.DISCONNECTED: '󰖪',
            NetState.PENDING: '󱛇',
            NetState.NEEDS_ATTENTION: '󱚵',
            NetState.UNKNOWN: '󰈅',
        }.get(net_state, '󰈅')
    store.dispatch(
        StatusIconsRegisterAction(
            icon=icon,
            priority=WIFI_STATE_ICON_PRIORITY,
            id=WIFI_STATE_ICON_ID,
        ),
    )


def _select_connections() -> bool:
    store.dispatch(WiFiUpdateRequestAction())
    return True


register_action('wifi:select-connections', _select_connections)



# --- Reactive state updates for the WiFi connection prompt ---


@store.autorun(lambda state: state.wifi.connections)
def _update_connection_prompt_state(
    connections: Sequence[WiFiConnection] | None,
) -> None:
    """Reactively update the WiFi connection prompt when state changes."""
    if connections is None:
        return

    connection_states = {c.ssid: c.state.value for c in connections}

    @store.with_state(lambda state: state.main.stack)
    def _check_stack(stack: tuple) -> None:
        top = stack[-1] if stack else None
        if not isinstance(top, PromptStackItem):
            return
        prompt = top.prompt
        if not prompt.startswith('SSID: '):
            return
        ssid = prompt[len('SSID: '):]
        new_state = connection_states.get(ssid)
        if new_state is not None:
            store.dispatch(
                UpdatePromptAction(
                    icon=_get_prompt_icon(new_state),
                    items=_build_prompt_items(ssid, new_state),
                ),
            )

    _check_stack()
