# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import asyncio

from debouncer import DebounceOptions, debounce
from pages import create_wireless_connection, main
from redux import ViewOptions
from ubo_gui.constants import INFO_COLOR
from wifi_manager import (
    get_connections,
    get_wifi_device,
    get_wifi_device_state,
    request_scan,
)

from ubo_app.logging import logger
from ubo_app.store.core import (
    RegisterSettingAppAction,
    SettingsCategory,
)
from ubo_app.store.main import dispatch, subscribe_event, view
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationActionItem,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.wifi import (
    ConnectionState,
    WiFiSetHasVisitedOnboardingAction,
    WiFiUpdateAction,
    WiFiUpdateRequestEvent,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.persistent_store import register_persistent_store


@debounce(
    wait=0.5,
    options=DebounceOptions(leading=True, trailing=False, time_window=2),
)
async def update_wifi_list(_: WiFiUpdateRequestEvent | None = None) -> None:
    connections = await get_connections()

    dispatch(
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


@view(
    lambda state: (state.ip.is_connected, state.wifi.has_visited_onboarding),
    options=ViewOptions(default_value=None),
)
def should_show_onboarding(state: tuple[bool | None, bool]) -> bool | None:
    is_connected, has_visited_onboarding = state
    if is_connected is None:
        return None
    return not is_connected and not has_visited_onboarding


def show_onboarding_notification() -> None:
    dispatch(
        NotificationsAddAction(
            notification=Notification(
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
                extra_information="""Press middle button to add {WiFi|W AY F AY} \
network with {QR|K Y UW AA R} code.\nIf you dismiss this, you can always add \
{WiFi|W AY F AY} network through Settings → Network → {WiFi|W AY F AY}""",
                color=INFO_COLOR,
            ),
        ),
        WiFiSetHasVisitedOnboardingAction(has_visited_onboarding=True),
    )


async def init_service() -> None:
    create_task(update_wifi_list())
    create_task(setup_listeners())

    register_persistent_store(
        'wifi_has_visited_onboarding',
        lambda state: state.wifi.has_visited_onboarding,
    )

    dispatch(
        RegisterSettingAppAction(
            priority=2,
            category=SettingsCategory.NETWORK,
            menu_item=main.WiFiMainMenu,
        ),
    )

    subscribe_event(WiFiUpdateRequestEvent, lambda: create_task(request_scan()))

    while should_show_onboarding() is None:
        await asyncio.sleep(1)
    if should_show_onboarding():
        logger.info('No internet connection, showing WiFi onboarding.')
        show_onboarding_notification()
