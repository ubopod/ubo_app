# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from debouncer import DebounceOptions, debounce
from pages import create_wireless_connection, main
from wifi_manager import (
    get_connections,
    get_wifi_device,
    get_wifi_device_state,
    request_scan,
)

from ubo_app.colors import INFO_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.types import (
    RegisterSettingAppAction,
    SettingsCategory,
)
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationActionItem,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.store.services.wifi import (
    ConnectionState,
    WiFiInputConnectionAction,
    WiFiInputConnectionEvent,
    WiFiSetHasVisitedOnboardingAction,
    WiFiUpdateAction,
    WiFiUpdateRequestEvent,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.eeprom import get_eeprom_data
from ubo_app.utils.network import get_saved_wifi_ssids, has_gateway
from ubo_app.utils.persistent_store import (
    read_from_persistent_store,
    register_persistent_store,
)

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
            NotificationActionItem(
                action=lambda: (
                    create_wireless_connection.CreateWirelessConnectionPage
                ),
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
        if get_eeprom_data() is not None:
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


def init_service() -> Subscriptions:
    create_task(update_wifi_list())
    create_task(setup_listeners())

    register_persistent_store(
        'wifi_has_visited_onboarding',
        lambda state: state.wifi.has_visited_onboarding,
    )

    store.dispatch(
        RegisterSettingAppAction(
            priority=2,
            category=SettingsCategory.NETWORK,
            menu_item=main.WiFiMainMenu,
        ),
    )

    create_task(_check_connection())

    return [
        store.subscribe_event(WiFiUpdateRequestEvent, request_scan),
        store.subscribe_event(
            WiFiInputConnectionEvent,
            create_wireless_connection.input_wifi_connection,
        ),
    ]
