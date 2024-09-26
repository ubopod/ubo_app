# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from debouncer import DebounceOptions, debounce
from pages import create_wireless_connection, main
from redux import AutorunOptions
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
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationActionItem,
    NotificationDisplayType,
    NotificationExtraInformation,
    NotificationsAddAction,
)
from ubo_app.store.services.wifi import (
    ConnectionState,
    WiFiSetHasVisitedOnboardingAction,
    WiFiUpdateAction,
    WiFiUpdateRequestEvent,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.persistent_store import (
    read_from_persistent_store,
    register_persistent_store,
)


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


ONBOARDING_NOTIFICATION = Notification(
    title='No internet connection',
    content='Press middle button "󱚾" to add WiFi network',
    importance=Importance.MEDIUM,
    icon='󱚵',
    display_type=NotificationDisplayType.STICKY,
    actions=[
        NotificationActionItem(
            action=lambda: (create_wireless_connection.CreateWirelessConnectionPage),
            icon='󱚾',
            background_color=INFO_COLOR,
            dismiss_notification=True,
        ),
    ],
    extra_information=NotificationExtraInformation(
        text='Press middle button to add WiFi network with QR code.\n'
        'If you dismiss this, you can always add WiFi network through '
        'Settings → Network → WiFi',
        piper_text='Press middle button to add WiFi network with QR code.\n'
        'If you dismiss this, you can always add WiFi network through '
        'Settings menu, by navigating to Network, and then WiFi',
        picovoice_text='Press middle button to add {WiFi|W AY F AY} '
        'network with {QR|K Y UW AA R} code.\n'
        'If you dismiss this, you can always add {WiFi|W AY F AY} network '
        'through Settings → Network → {WiFi|W AY F AY}',
    ),
    color=INFO_COLOR,
)


def show_onboarding_notification() -> None:
    store.dispatch(
        NotificationsAddAction(
            notification=ONBOARDING_NOTIFICATION,
        ),
    )


async def init_service() -> None:
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

    store.subscribe_event(WiFiUpdateRequestEvent, request_scan)

    @store.autorun(
        lambda state: state.ip.is_connected,
        options=AutorunOptions(default_value=None),
    )
    def check_onboarding(is_connected: bool | None) -> None:
        try:
            _ = check_onboarding
        except NameError:
            return

        if is_connected is False and not read_from_persistent_store(
            key='wifi_has_visited_onboarding',
            default=False,
        ):
            logger.info('No internet connection, showing WiFi onboarding.')
            show_onboarding_notification()
            store.dispatch(
                WiFiSetHasVisitedOnboardingAction(has_visited_onboarding=True),
            )

        if is_connected is not None:
            check_onboarding.unsubscribe()
