# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from pathlib import Path

from debouncer import DebounceOptions, debounce
from wifi_manager import (
    add_wireless_connection,
    get_connections,
    get_wifi_device,
    get_wifi_device_state,
    request_scan,
)

from ubo_app.logging import logger
from ubo_app.store import dispatch, subscribe_event
from ubo_app.store.app import RegisterSettingAppAction
from ubo_app.store.wifi import (
    ConnectionState,
    WiFiCreateEvent,
    WiFiType,
    WiFiUpdateAction,
    WiFiUpdateRequestAction,
    WiFiUpdateRequestEvent,
)
from ubo_app.utils.async_ import create_task

IS_RPI = Path('/etc/rpi-issue').exists()


def create_wifi_connection(event: WiFiCreateEvent) -> None:
    connection = event.connection
    ssid = connection.ssid
    password = connection.password

    if not password:
        logger.warn('Password is required')
        return

    async def act() -> None:
        await add_wireless_connection(
            ssid=ssid,
            password=password,
            type=connection.type or WiFiType.nopass,
            hidden=connection.hidden,
        )

        logger.info('Result of running `add_wifi`')

        dispatch(
            WiFiUpdateRequestAction(reset=True),
        )

    create_task(act())


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


def init_service() -> None:
    from pages import main

    create_task(update_wifi_list())
    create_task(setup_listeners())

    dispatch(
        [
            RegisterSettingAppAction(
                menu_item=main.WiFiMainMenu,
            ),
        ],
    )

    subscribe_event(WiFiCreateEvent, create_wifi_connection)
    subscribe_event(WiFiUpdateRequestEvent, lambda _: create_task(request_scan()))
