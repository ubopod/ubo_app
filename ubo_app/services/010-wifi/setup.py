# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from debouncer import DebounceOptions, debounce
from wifi_manager import (
    get_connections,
    get_wifi_device,
    get_wifi_device_state,
    request_scan,
)

from ubo_app.store import dispatch, subscribe_event
from ubo_app.store.main import RegisterSettingAppAction
from ubo_app.store.services.wifi import (
    ConnectionState,
    WiFiUpdateAction,
    WiFiUpdateRequestEvent,
)
from ubo_app.utils.async_ import create_task


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

    dispatch(RegisterSettingAppAction(menu_item=main.WiFiMainMenu))

    subscribe_event(WiFiUpdateRequestEvent, lambda _: create_task(request_scan()))
