"""Test the wireless flow."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import TYPE_CHECKING

import pytest
from tenacity import wait_fixed

from ubo_app.store.services.wifi import (
    ConnectionState,
    GlobalWiFiState,
    WiFiConnection,
    WiFiState,
)
from ubo_app.utils import IS_RPI

if TYPE_CHECKING:
    from headless_kivy_pi_pytest.fixtures import WindowSnapshot
    from redux_pytest.fixtures import StoreSnapshot, WaitFor

    from tests.fixtures import (
        AppContext,
        LoadServices,
        MockCamera,
        Stability,
    )
    from tests.fixtures.menu import WaitForEmptyMenu, WaitForMenuItem
    from ubo_app.store.main import RootState


def store_snapshot_selector(state: RootState) -> WiFiState | None:
    """Select the store snapshot."""
    wifi_state = state.wifi

    if (
        any(
            connection.state is ConnectionState.CONNECTING
            for connection in wifi_state.connections or []
        )
        or wifi_state.state is GlobalWiFiState.PENDING
    ):
        # Connecting state does not happen consistently in multiple runs
        return None

    return WiFiState(
        connections=[
            WiFiConnection(
                **dict(
                    asdict(connection),
                    signal_strength=100 if connection.signal_strength > 0 else 0,
                ),
            )
            for connection in wifi_state.connections
        ]
        if wifi_state.connections is not None
        else None,
        state=wifi_state.state,
        current_connection=WiFiConnection(
            **dict(
                asdict(wifi_state.current_connection),
                signal_strength=100
                if wifi_state.current_connection.signal_strength > 0
                else 0,
            ),
        )
        if wifi_state.current_connection is not None
        else None,
        has_visited_onboarding=wifi_state.has_visited_onboarding,
    )


@pytest.mark.skipif(not IS_RPI, reason='Not running on Raspberry Pi')
async def test_wireless_flow(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot[RootState],
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
    needs_finish: None,
    camera: MockCamera,
    wait_for_menu_item: WaitForMenuItem,
    wait_for_empty_menu: WaitForEmptyMenu,
) -> None:
    """Test the wireless flow."""
    _ = needs_finish
    from ubo_app.menu_app.menu import MenuApp
    from ubo_app.store.core import ChooseMenuItemByIconEvent, ChooseMenuItemByLabelEvent
    from ubo_app.store.main import dispatch, store
    from ubo_app.store.services.keypad import Key, KeypadKeyPressAction

    store_snapshot.monitor(store_snapshot_selector)

    app = MenuApp()
    app_context.set_app(app)
    load_services(['camera', 'wifi', 'notifications'])

    @wait_for(timeout=5.0, wait=wait_fixed(0.5), run_async=True)
    def check_icon() -> None:
        state = store._state  # noqa: SLF001

        assert state is not None

        icon = next(
            (icon for icon in state.status_icons.icons if icon.id == 'wifi:state'),
            None,
        )

        assert icon is not None, 'wifi icon not registered'
        assert icon.symbol != '󰖩', 'wifi is already connected'
        assert icon.symbol == '󰖪', f'unexpected wifi icon {icon.symbol}'

    await check_icon()
    await stability()

    # Select the main menu
    dispatch(ChooseMenuItemByIconEvent(icon='󰍜'))
    await stability()

    # Select the settings menu
    dispatch(ChooseMenuItemByLabelEvent(label='Settings'))
    await stability()

    # Go to network category
    dispatch(ChooseMenuItemByLabelEvent(label='Network'))
    await stability()

    # Open the wireless menu
    dispatch(ChooseMenuItemByLabelEvent(label='WiFi'))
    await stability()
    window_snapshot.take()

    # Select "Select" to open the wireless connection list
    dispatch(ChooseMenuItemByLabelEvent(label='Select'))
    await stability()

    # Back to the wireless menu
    dispatch(KeypadKeyPressAction(key=Key.BACK))
    await stability()

    # Select "Add" to add a new connection
    dispatch(ChooseMenuItemByLabelEvent(label='Add'))
    await stability()
    window_snapshot.take()

    # Set QR Code image of the WiFi credentials before camera is started
    camera.set_image('qrcode/wifi')

    # Select "QR code" to scan a QR code for credentials
    dispatch(ChooseMenuItemByIconEvent(icon='󰄀'))

    # Success notification should be shown
    window_snapshot.take()

    # Dismiss the notification informing the user that the connection was added
    await wait_for_menu_item(label='', icon='󰆴')
    dispatch(ChooseMenuItemByIconEvent(icon='󰆴'))
    await stability()

    # Select "Select" to open the wireless connection list and see the new connection
    dispatch(ChooseMenuItemByLabelEvent(label='Select'))

    @wait_for(timeout=5.0, wait=wait_fixed(0.5), run_async=True)
    def check_connections() -> None:
        state = store._state  # noqa: SLF001

        assert state is not None
        assert state.wifi.connections is not None

    await check_connections()
    await wait_for_menu_item(label='ubo-test-ssid', icon='󱚽', timeout=20)
    window_snapshot.take()

    # Select the connection
    dispatch(ChooseMenuItemByLabelEvent(label='ubo-test-ssid'))

    # Wait for the "Disconnect" item to show up
    await wait_for_menu_item(label='Disconnect')
    await stability()
    window_snapshot.take()
    dispatch(ChooseMenuItemByLabelEvent(label='Disconnect'))

    # Wait for the "Connect" item to show up
    await wait_for_menu_item(label='Connect')
    await stability()
    window_snapshot.take()
    dispatch(ChooseMenuItemByLabelEvent(label='Connect'))

    await wait_for_menu_item(label='Disconnect')
    await stability()
    window_snapshot.take()
    dispatch(ChooseMenuItemByLabelEvent(label='Delete'))

    # Dismiss the notification informing the user that the connection was deleted
    await wait_for_menu_item(label='', icon='󰆴')
    window_snapshot.take()
    dispatch(ChooseMenuItemByIconEvent(icon='󰆴'))

    @wait_for(timeout=5.0, wait=wait_fixed(0.5), run_async=True)
    def check_no_connections() -> None:
        state = store._state  # noqa: SLF001
        assert state
        assert state.wifi.connections == []

    await check_no_connections()
    await stability()

    await wait_for_empty_menu(placeholder='No Wi-Fi connections found')
    await asyncio.sleep(1)
    window_snapshot.take()
