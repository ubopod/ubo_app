# ruff: noqa: D100, D103
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from debouncer import DebounceOptions, debounce
from pages import create_wireless_connection
from wifi_manager import (
    get_connections,
    get_wifi_device,
    get_wifi_device_state,
    request_scan,
)

from ubo_app.colors import INFO_COLOR, SUCCESS_COLOR
from ubo_app.constants import WEB_UI_HOTSPOT_PASSWORD
from ubo_app.logger import logger
from ubo_app.store.core.types import (
    OpenRenderAction,
    RegisterSettingAppAction,
    SettingsCategory,
)
from ubo_app.store.input.types import InputMethod
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationDispatchItem,
    NotificationDisplayType,
    NotificationsAddAction,
    NotificationsClearEvent,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.store.services.wifi import (
    ConnectionState,
    WiFiInputConnectionAction,
    WiFiInputConnectionEvent,
    WiFiSetHasVisitedOnboardingAction,
    WiFiSetHotspotRunningAction,
    WiFiStartHotspotEvent,
    WiFiStopHotspotAction,
    WiFiStopHotspotEvent,
    WiFiUpdateAction,
    WiFiUpdateRequestEvent,
)
from ubo_app.utils import IS_UBO_POD
from ubo_app.utils.async_ import create_task
from ubo_app.utils.hotspot_qr import hotspot_qr_action, pop_hotspot_qr_render
from ubo_app.utils.network import get_saved_wifi_ssids, has_gateway
from ubo_app.utils.persistent_store import (
    read_from_persistent_store,
    register_persistent_store,
)
from ubo_app.utils.pod_id import get_pod_id
from ubo_app.utils.server import send_command

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions


@debounce(
    wait=0.5,
    options=DebounceOptions(leading=True, trailing=False, time_window=0.5),
)
async def update_wifi_list(_: WiFiUpdateRequestEvent | None = None) -> None:
    connections = await get_connections()

    store.dispatch(
        WiFiUpdateAction(
            connections=connections,
            state=await get_wifi_device_state(),
            current_connection=next(
                (
                    connection
                    for connection in connections
                    if connection.state is ConnectionState.CONNECTED
                ),
                None,
            ),
        ),
    )


async def setup_listeners() -> None:
    wifi_device = await get_wifi_device()
    if not wifi_device:
        return

    async for _ in wifi_device.properties_changed:
        create_task(update_wifi_list())


async def _check_connection() -> None:
    """Dispatch the Wi-Fi input action if needed."""
    await asyncio.sleep(2)
    logger.info(
        'Checking Wi-Fi',
        extra={
            'has_gateway': await has_gateway(),
            'saved_wifi_ssids': await get_saved_wifi_ssids(),
        },
    )
    onboarding_notification = Notification(
        title='No internet connection',
        content='Press middle button "󱚾" to add WiFi network',
        importance=Importance.MEDIUM,
        icon='󱚵',
        display_type=NotificationDisplayType.STICKY,
        actions=[
            NotificationDispatchItem(
                store_action=OpenRenderAction(
                    kind='status',
                    title='Creating WiFi Connection',
                    props={
                        'icon': '󱛃',
                        'text': 'Creating Scanned WiFi Connection',
                        'icon_size': 56,
                        'text_font_size': 19,
                    },
                ),
                label='Add WiFi',
                icon='󱚾',
                background_color=INFO_COLOR,
                dismiss_notification=True,
            ),
        ],
        extra_information=ReadableInformation(
            text='Press middle button to add a WiFi connection.\n'
            'If you dismiss this, you can always add WiFi through Settings → Network → '
            'WiFi.',
            piper_text='Press middle button to add a WiFi connection. '
            'If you dismiss this, you can always add WiFi through Settings menu, by '
            'navigating to Network, and then WiFi.',
            picovoice_text='Press middle button to add a {WiFi|W AY F AY} connection. '
            'If you dismiss this, you can always add {WiFi|W AY F AY} through Settings '
            '→ Network → {WiFi|W AY F AY}.',
        ),
        color=INFO_COLOR,
    )
    if not await has_gateway() and not await get_saved_wifi_ssids():
        if IS_UBO_POD:
            if not read_from_persistent_store(
                key='wifi_has_visited_onboarding',
                default=False,
            ):
                logger.info('No network connection found, showing WiFi onboarding.')
                store.dispatch(
                    NotificationsAddAction(
                        notification=onboarding_notification,
                    ),
                    WiFiSetHasVisitedOnboardingAction(has_visited_onboarding=True),
                )
        else:
            logger.info('No network connection found, prompting for Wi-Fi input.')
            store.dispatch(WiFiInputConnectionAction())


_HOTSPOT_ACTIVE_NOTIFICATION_ID = 'wifi:hotspot-active'


async def _start_hotspot(mode: str = 'captive', *, user_enabled: bool = False) -> bool:
    """Start the hotspot in ``mode`` and sync tracked state. Returns success.

    ``user_enabled`` marks a deliberately toggled-on hotspot so the route-driven
    auto-stop leaves it up (essential for an internet-sharing hotspot, which is
    up precisely while the device has an upstream route).
    """
    result = await send_command('hotspot', 'start', mode, has_output=True)
    success = result == 'done'
    store.dispatch(
        WiFiSetHotspotRunningAction(
            is_running=success,
            user_enabled=user_enabled and success,
        ),
    )
    return success


def _hotspot_error_notification(content: str) -> NotificationsAddAction:
    return NotificationsAddAction(
        notification=Notification(
            id='wifi:hotspot_error',
            icon='󱋆',
            title='Hotspot Error',
            content=content,
            display_type=NotificationDisplayType.STICKY,
            importance=Importance.HIGH,
        ),
    )


def _hotspot_connect_notification() -> Notification:
    """Standalone 'hotspot is on' notification (settings toggle) with a QR + steps."""
    pod_id = get_pod_id(with_default=True)
    return Notification(
        id=_HOTSPOT_ACTIVE_NOTIFICATION_ID,
        icon='󰖩',
        title='WiFi Hotspot',
        content='Hotspot is on',
        display_type=NotificationDisplayType.STICKY,
        is_read=True,
        color=SUCCESS_COLOR,
        actions=[hotspot_qr_action()],
        extra_information=ReadableInformation(
            text=f'Connect to the "{pod_id}" WiFi network with password '
            f'"{WEB_UI_HOTSPOT_PASSWORD}", or scan the WiFi QR.',
        ),
    )


async def start_hotspot(event: WiFiStartHotspotEvent) -> None:
    """Explicitly start the hotspot (settings toggle)."""
    logger.info('wifi - start hotspot', extra={'mode': event.mode})
    if not await _start_hotspot(event.mode, user_enabled=True):
        store.dispatch(
            _hotspot_error_notification(
                'Failed to start the hotspot, please check the logs.',
            ),
        )
        return
    # Toggle-on has no input demand, so surface how to connect (steps + QR).
    store.dispatch(NotificationsAddAction(notification=_hotspot_connect_notification()))


async def stop_hotspot(_: WiFiStopHotspotEvent) -> None:
    """Tear the hotspot down and restore managed Wi-Fi."""
    logger.info('wifi - stop hotspot')
    result = await send_command('hotspot', 'stop', has_output=True)
    store.dispatch(WiFiSetHotspotRunningAction(is_running=False))
    if result != 'done':
        logger.error('Failed to stop the hotspot cleanly', extra={'result': result})


def _close_hotspot_qr_on_notification_cleared(
    event: NotificationsClearEvent,
) -> None:
    """Drop the QR page once the hotspot connect notification is cleared."""
    if event.notification.id == _HOTSPOT_ACTIVE_NOTIFICATION_ID:
        pop_hotspot_qr_render()


def init_service() -> Subscriptions:
    create_task(update_wifi_list())
    create_task(setup_listeners())

    @store.autorun(
        lambda state: (
            # Guarded: the ip service may not be loaded (e.g. in focused tests),
            # in which case connectivity is unknown and we must not auto-stop.
            state.ip.is_connected if hasattr(state, 'ip') else None,
            state.wifi.is_hotspot_running,
            state.wifi.hotspot_user_enabled,
        ),
    )
    def _stop_hotspot_when_connected(data: tuple[bool | None, bool, bool]) -> None:
        """Bring a *transient* hotspot down once the device gets a real route.

        ``ip.is_connected`` is ping-based internet reachability, so the hotspot's
        own 192.168.4.1 link never trips it - it only fires on a genuine route.
        This only tears down the transient onboarding/captive hotspot; a
        deliberately toggled-on hotspot (``hotspot_user_enabled``) is left up so
        an internet-sharing hotspot survives having an upstream route.
        """
        is_connected, is_hotspot_running, user_enabled = data
        if is_connected and is_hotspot_running and not user_enabled:
            store.dispatch(WiFiStopHotspotAction())

    register_persistent_store(
        'wifi_has_visited_onboarding',
        lambda state: state.wifi.has_visited_onboarding,
    )

    store.dispatch(
        RegisterSettingAppAction(
            priority=2,
            category=SettingsCategory.NETWORK,
            label='WiFi',
            icon='󰖩',
        ),
    )

    # Register path matchers for WiFi menu navigation
    from constants import (
        WIFI_CONNECTIONS_MENU_ID,
        WIFI_SCAN_MENU_ID,
        WIFI_SETTINGS_MENU_ID,
    )

    from ubo_app.store.core.view_registry import (
        create_settings_path_matcher,
        register_path_menu_matcher,
    )

    unregister_settings_matcher = register_path_menu_matcher(
        'wifi:settings',
        create_settings_path_matcher('wifi:', WIFI_SETTINGS_MENU_ID),
    )

    # Ad-hoc scan-results menu pushed imperatively during hotspot onboarding;
    # resolve it whenever it is the current (top) frame, wherever it is pushed.
    unregister_scan_matcher = register_path_menu_matcher(
        'wifi:hotspot-scan',
        lambda path: WIFI_SCAN_MENU_ID
        if path and path[-1] == WIFI_SCAN_MENU_ID
        else None,
        priority=1,
    )

    min_connections_path_length = 5

    unregister_connections_matcher = register_path_menu_matcher(
        'wifi:connections',
        lambda path: WIFI_CONNECTIONS_MENU_ID
        if len(path) >= min_connections_path_length
        and path[3] == 'wifi:'
        and path[4] == 'wifi:connections'
        else None,
        priority=1,
    )

    # Import pages/main to set up dynamic menus and action handlers
    from pages import main as _pages_main  # noqa: F401

    unregister_scan_handler = create_wireless_connection.register_scan_action_handler()

    create_task(_check_connection())

    return [
        unregister_settings_matcher,
        unregister_scan_matcher,
        unregister_connections_matcher,
        unregister_scan_handler,
        store.subscribe_event(WiFiUpdateRequestEvent, request_scan),
        store.subscribe_event(
            WiFiInputConnectionEvent,
            lambda: create_wireless_connection.input_wifi_connection(
                input_methods=(InputMethod.WEB_DASHBOARD,),
            ),
        ),
        store.subscribe_event(WiFiStartHotspotEvent, start_hotspot),
        store.subscribe_event(WiFiStopHotspotEvent, stop_hotspot),
        store.subscribe_event(
            NotificationsClearEvent,
            _close_hotspot_qr_on_notification_cleared,
        ),
    ]
