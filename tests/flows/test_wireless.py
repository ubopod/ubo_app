"""Test the wireless flow."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tenacity import wait_fixed

from ubo_app.utils import IS_RPI

if TYPE_CHECKING:
    from headless_kivy_pytest.fixtures import WindowSnapshot
    from redux_pytest.fixtures import StoreSnapshot, WaitFor

    from tests.fixtures import (
        AppContext,
        LoadServices,
        MockCamera,
        Stability,
    )
    from tests.fixtures.menu import WaitForEmptyMenu, WaitForMenuItem
    from ubo_app.store.main import RootState
    from ubo_app.store.services.wifi import WiFiState


@pytest.mark.skipif(not IS_RPI, reason='Only runs on Raspberry Pi')
async def test_wireless_flow(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot[RootState],
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
    camera: MockCamera,
    wait_for_menu_item: WaitForMenuItem,
    wait_for_empty_menu: WaitForEmptyMenu,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test the wireless flow."""
    from sdbus_async.networkmanager import (  # pyright: ignore [reportMissingModuleSource]
        AccessPoint,
    )

    async def strength() -> int:
        return 100

    monkeypatch.setattr(
        AccessPoint,
        'strength',
        property(lambda self: (self, strength())[1]),
    )

    from ubo_app.menu_app.menu import MenuApp
    from ubo_app.store.core import ChooseMenuItemByIconEvent, ChooseMenuItemByLabelEvent
    from ubo_app.store.main import store
    from ubo_app.store.services.keypad import Key, KeypadKeyPressAction

    def store_snapshot_selector(state: RootState) -> WiFiState:
        return state.wifi

    app = MenuApp()
    app_context.set_app(app)
    load_services(['camera', 'display', 'notifications', 'wifi'])

    @wait_for(wait=wait_fixed(1), run_async=True)
    def check_icon(expected_icon: str) -> None:
        state = store._state  # noqa: SLF001

        assert state is not None

        icon = next(
            (icon for icon in state.status_icons.icons if icon.id == 'wifi:state'),
            None,
        )

        assert icon is not None, 'wifi icon not registered'
        assert icon.symbol == expected_icon

    await check_icon('󰖪')

    await stability()
    store_snapshot.take(selector=store_snapshot_selector)

    # Select the main menu
    store.dispatch(ChooseMenuItemByIconEvent(icon='󰍜'))
    await stability()

    # Select the settings menu
    store.dispatch(ChooseMenuItemByLabelEvent(label='Settings'))
    await stability()

    # Go to network category
    store.dispatch(ChooseMenuItemByLabelEvent(label='Network'))
    await stability()

    # Open the wireless menu
    store.dispatch(ChooseMenuItemByLabelEvent(label='WiFi'))
    await stability()
    window_snapshot.take()

    # Select "Select" to open the wireless connection list
    store.dispatch(ChooseMenuItemByLabelEvent(label='Select'))
    await stability()

    # Back to the wireless menu
    store.dispatch(KeypadKeyPressAction(key=Key.BACK))
    await stability()

    # Select "Add" to add a new connection
    store.dispatch(ChooseMenuItemByLabelEvent(label='Add'))
    await stability()
    window_snapshot.take()

    # Set QR Code image of the WiFi credentials before camera is started
    camera.set_image('qrcode/wifi')

    # Select "QR code" to scan a QR code for credentials
    store.dispatch(ChooseMenuItemByIconEvent(icon='󰄀'))

    # Success notification should be shown
    window_snapshot.take()

    # Dismiss the notification informing the user that the connection was added
    await check_icon('󰤨')
    await wait_for_menu_item(label='', icon='󰆴')
    store.dispatch(ChooseMenuItemByIconEvent(icon='󰆴'))
    await stability()

    # Select "Select" to open the wireless connection list and see the new connection
    store.dispatch(ChooseMenuItemByLabelEvent(label='Select'))

    @wait_for(wait=wait_fixed(1), run_async=True)
    def check_connections() -> None:
        state = store._state  # noqa: SLF001

        assert state is not None
        assert state.wifi.connections is not None

    await check_connections()
    await wait_for_menu_item(label='ubo-test-ssid', icon='󱚽')
    store_snapshot.take(selector=store_snapshot_selector)
    window_snapshot.take()

    # Select the connection
    store.dispatch(ChooseMenuItemByLabelEvent(label='ubo-test-ssid'))

    # Wait for the "Disconnect" item to show up
    await wait_for_menu_item(label='Disconnect')
    await stability()
    window_snapshot.take()
    store.dispatch(ChooseMenuItemByLabelEvent(label='Disconnect'))

    # Wait for the "Connect" item to show up
    await wait_for_menu_item(label='Connect')
    await check_icon('󰖪')
    await stability()
    store_snapshot.take(selector=store_snapshot_selector)
    window_snapshot.take()
    store.dispatch(ChooseMenuItemByLabelEvent(label='Connect'))

    await wait_for_menu_item(label='Disconnect')
    await check_icon('󰤨')
    await stability()
    store_snapshot.take(selector=store_snapshot_selector)
    window_snapshot.take()
    store.dispatch(ChooseMenuItemByLabelEvent(label='Delete'))

    @wait_for(wait=wait_fixed(1), run_async=True)
    def check_no_connections() -> None:
        state = store._state  # noqa: SLF001
        assert state
        assert state.wifi.connections == []

    await check_no_connections()
    await check_icon('󰖪')
    store_snapshot.take(selector=store_snapshot_selector)

    # Dismiss the notification informing the user that the connection was deleted
    await wait_for_menu_item(label='', icon='󰆴')
    window_snapshot.take()
    store.dispatch(ChooseMenuItemByIconEvent(icon='󰆴'))

    await wait_for_empty_menu(placeholder='No Wi-Fi connections found')
    window_snapshot.take()
    store_snapshot.take(selector=store_snapshot_selector)
