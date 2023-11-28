# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from ubo_app.logging import logger
from ubo_app.store import dispatch, subscribe_event
from ubo_app.store.app import RegisterAppActionPayload, RegisterSettingAppAction
from ubo_app.store.status_icons import (
    StatusIconsRegisterAction,
    StatusIconsRegisterActionPayload,
)
from ubo_app.store.wifi import (
    WiFiConnection,
    WiFiCreateEvent,
    WiFiUpdateAction,
    WiFiUpdateActionPayload,
    WiFiUpdateEvent,
)

from .pages.main import WiFiMainMenu
from .wifi_manager import wifi_manager


def create_wifi_connection(event: WiFiCreateEvent) -> None:
    connection = event.payload.connection
    connection_type = connection.type

    if not connection_type:
        logger.warn('Connection type is required', {'provided_type': connection_type})
        return

    connection_type = connection_type.upper()

    if connection_type not in ('WPA', 'WEP', 'OPEN'):
        logger.warn('Connection type is not valid', {'provided_type': connection_type})
        return

    result = wifi_manager.add_wifi(
        ssid=connection.ssid,
        password=connection.password,
        type=connection_type,
    )

    logger.info('Result of running `add_wifi`', {'result': result})

    dispatch(WiFiUpdateEvent())


def update_wifi_list(_event: WiFiUpdateEvent | None = None) -> None:
    connections = [
        WiFiConnection(ssid=network['ssid']) for network in wifi_manager.list_networks()
    ]
    current_ssid, _ = wifi_manager.get_current_network() or ('', '')
    dispatch(
        WiFiUpdateAction(
            payload=WiFiUpdateActionPayload(
                connections=connections,
                is_on=True,
                current_connection=next(
                    (
                        connection
                        for connection in connections
                        if connection.ssid == current_ssid
                    ),
                    None,
                ),
            ),
        ),
    )


def init_service() -> None:
    dispatch(
        [
            RegisterSettingAppAction(
                payload=RegisterAppActionPayload(menu_item=WiFiMainMenu),
            ),
            StatusIconsRegisterAction(
                payload=StatusIconsRegisterActionPayload(icon='wifi', priority=-1),
            ),
        ],
    )

    subscribe_event(WiFiCreateEvent, create_wifi_connection)
    subscribe_event(WiFiUpdateEvent, update_wifi_list)


if __name__ == '__ubo_service__':
    init_service()
