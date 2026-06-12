"""Test the wireless flow."""

from __future__ import annotations

from itertools import cycle
from typing import TYPE_CHECKING

import pytest

from ubo_app.utils import IS_RPI

if TYPE_CHECKING:
    from redux_pytest.fixtures import StoreSnapshot, WaitFor

    from tests.fixtures import (
        AppContext,
        Dispatcher,
        LoadServices,
        MockCamera,
        Stability,
    )
    from tests.fixtures.menu import WaitForEmptyMenu, WaitForMenuItem
    from tests.fixtures.snapshot import WindowSnapshot
    from ubo_app.store.main import RootState
    from ubo_app.store.services.wifi import WiFiState

from tests.fixtures.dispatch import DIRECT, GRPC_KEYPAD, GRPC_MENU


@pytest.fixture(autouse=True, scope='module')
def _wifi_clean_slate() -> None:
    """Reset NetworkManager Wi-Fi state once before the Wi-Fi test (RPi only).

    Runs ``tests/flows/wifi_setup.sh`` a single time for this module instead of
    the old ``tests/setup.sh`` that the autouse ``_setup_script`` walk executed
    for *every* test in the suite. Off-device the script is a no-op.
    """
    import subprocess
    from pathlib import Path

    if not IS_RPI:
        return
    script = Path(__file__).parent / 'wifi_setup.sh'
    subprocess.run(['/usr/bin/env', 'bash', str(script)], check=True)  # noqa: S603


@pytest.mark.timeout(250)
@pytest.mark.skipif(not IS_RPI, reason='Only runs on Raspberry Pi')
async def test_setup_flow(
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
    dispatcher: Dispatcher,
) -> None:
    """Test the wireless flow."""
    from sdbus_async.networkmanager import (  # pyright: ignore [reportMissingModuleSource]
        AccessPoint,
    )
    from tenacity import wait_fixed

    async def strength() -> int:
        return 100

    monkeypatch.setattr(
        AccessPoint,
        'strength',
        property(lambda self: (self, strength())[1]),
    )

    from ubo_app.store.main import store

    def store_snapshot_selector(state: RootState) -> WiFiState:
        return state.wifi

    app_context.set_app()
    unload_waiter = await load_services(
        ['camera', 'display', 'keypad', 'notifications', 'wifi'],
        run_async=True,
    )

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

    @wait_for(wait=wait_fixed(1), run_async=True)
    def check_connection_page(expected_state: str) -> None:  # noqa: ARG001
        from ubo_app.store.core.types import PromptViewData

        state = store._state  # noqa: SLF001
        assert state is not None

        current_view = state.main.current_view
        assert isinstance(current_view, PromptViewData)
        assert 'ubo-test-ssid' in current_view.prompt

    await check_icon('󰖪')

    await stability(initial_wait=2, timeout=30)

    store_snapshot.take(selector=store_snapshot_selector)

    # Round-robin through all three dispatch modes
    via = cycle([DIRECT, GRPC_MENU, GRPC_KEYPAD])

    # Select the main menu
    await dispatcher.choose_by_icon('󰍜', via=next(via))  # direct
    await wait_for_menu_item(label='Settings')

    # Select the settings menu
    await dispatcher.choose_by_label('Settings', via=next(via))  # grpc_menu
    await wait_for_menu_item(label='Network')

    # Go to network category
    await dispatcher.choose_by_label('Network', via=next(via))  # grpc_keypad
    await wait_for_menu_item(label='WiFi')

    # Open the wireless menu
    await dispatcher.choose_by_label('WiFi', via=next(via))  # direct
    await wait_for_menu_item(label='Select')
    await stability()
    window_snapshot.take()

    # Select "Select" to open the wireless connection list
    await dispatcher.choose_by_label('Select', via=next(via))  # grpc_menu
    await stability()

    # Back to the wireless menu
    await dispatcher.go_back(via=next(via))  # grpc_keypad
    await wait_for_menu_item(label='Select')
    await stability()

    # Select "Add" to add a new connection
    await dispatcher.choose_by_label('Add', via=next(via))  # direct
    await wait_for_menu_item(icon='󰄀')
    await stability()

    # Input method selection should be shown
    window_snapshot.take()

    # Set QR Code image of the WiFi credentials before camera is started
    camera.set_image('qrcode/wifi')

    # Select "QR code" input method (triggers camera service notification
    # as an intermediate step, so use stability() instead of wait_for_menu_item)
    await dispatcher.choose_by_icon('󰄀', via=next(via))  # grpc_menu
    await stability()

    # QR code instructions should be shown
    window_snapshot.take()

    # Select "QR code" to scan a QR code for credentials
    await dispatcher.choose_by_icon('󰄀', via=next(via))  # grpc_keypad

    # The QR flow emits the "Added" flash notification as soon as the
    # connection profile is created. Activation can lag behind that on hidden
    # networks, so wait for the notification first instead of the connected
    # status icon.
    await wait_for_menu_item(label='Dismiss', icon='')
    await check_icon('󰤨')
    window_snapshot.take()
    await dispatcher.choose_by_icon('', via=next(via))  # direct
    await stability()

    # Select "Select" to open the wireless connection list and see the new connection
    await dispatcher.choose_by_label('Select', via=next(via))  # grpc_menu

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
    await dispatcher.choose_by_label('ubo-test-ssid', via=next(via))  # grpc_keypad

    # WiFi connection details open as an application view, not a menu.
    await check_connection_page('Connected')
    await stability()
    window_snapshot.take()
    await dispatcher.app_button(1, via=next(via))  # direct

    await check_connection_page('Disconnected')
    await check_icon('󰖪')
    await stability()
    store_snapshot.take(selector=store_snapshot_selector)
    window_snapshot.take()
    await dispatcher.app_button(1, via=next(via))  # grpc_menu

    await check_connection_page('Connected')
    await check_icon('󰤨')
    await stability()
    store_snapshot.take(selector=store_snapshot_selector)
    window_snapshot.take()
    await dispatcher.app_button(2, via=next(via))  # grpc_keypad

    @wait_for(wait=wait_fixed(1), run_async=True)
    def check_no_connections() -> None:
        state = store._state  # noqa: SLF001
        assert state
        assert state.wifi.connections == []

    await check_no_connections()
    await check_icon('󰖪')
    store_snapshot.take(selector=store_snapshot_selector)

    # Dismiss the notification informing the user that the connection was deleted
    await wait_for_menu_item(label='Dismiss', icon='')
    window_snapshot.take()
    await dispatcher.choose_by_icon('', via=next(via))  # direct

    await wait_for_empty_menu(placeholder='No Wi-Fi connections found')
    window_snapshot.take()
    store_snapshot.take(selector=store_snapshot_selector)

    await unload_waiter()
