# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import time
from pathlib import Path

from wifi_manager import (
    add_wireless_connection,
    get_connections,
    get_wifi_device,
    request_scan,
)

from ubo_app.logging import logger
from ubo_app.store import dispatch, subscribe_event
from ubo_app.store.app import RegisterSettingAppAction
from ubo_app.store.status_icons import StatusIconsRegisterAction
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
REFRESH_TIMEOUT = 10


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


async def update_wifi_list(_: WiFiUpdateRequestEvent | None = None) -> None:
    connections = await get_connections()
    dispatch(
        WiFiUpdateAction(
            connections=connections,
            is_on=True,
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


def init_service() -> None:
    from pages import main

    async def setup_listeners() -> None:
        last_update_time = time.time()

        wifi_device = await get_wifi_device()
        if not wifi_device:
            return

        async for _ in wifi_device.properties_changed:
            if time.time() - last_update_time < REFRESH_TIMEOUT:
                return
            last_update_time = time.time()
            create_task(update_wifi_list())

    create_task(update_wifi_list())
    create_task(setup_listeners())

    dispatch(
        [
            RegisterSettingAppAction(
                menu_item=main.WiFiMainMenu,
            ),
            StatusIconsRegisterAction(
                icon='wifi',
                priority=-1,
            ),
        ],
    )

    subscribe_event(WiFiCreateEvent, create_wifi_connection)
    subscribe_event(WiFiUpdateRequestEvent, lambda _: create_task(request_scan()))
