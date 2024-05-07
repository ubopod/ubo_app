"""Test the wireless flow."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import ANY

from tenacity import stop_after_delay

if TYPE_CHECKING:
    from redux_pytest.fixtures import StoreMonitor, StoreSnapshot, WaitFor

    from tests.fixtures import AppContext, LoadServices, Stability, WindowSnapshot


async def test_wireless_flow(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot,
    store_monitor: StoreMonitor,
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
    needs_finish: None,
) -> None:
    """Test the wireless flow."""
    _ = needs_finish
    from ubo_app.menu_app.menu import MenuApp
    from ubo_app.store import dispatch, store
    from ubo_app.store.services.camera import CameraStartViewfinderAction
    from ubo_app.store.services.keypad import Key, KeypadKeyPressAction

    app = MenuApp()
    app_context.set_app(app)
    load_services(['wifi', 'notifications'])

    @wait_for(timeout=5.0, run_async=True)
    def check_icon() -> None:
        state = store._state  # noqa: SLF001

        assert state is not None

        assert any(
            icon.id == 'wifi:state' and icon.symbol == '󰖪'
            for icon in state.status_icons.icons
        ), 'wifi icon not registered'

    await check_icon()
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    # Press the L1 key to open the main menu
    dispatch(KeypadKeyPressAction(key=Key.L1))
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    # Press the L2 key to open the settings menu
    dispatch(KeypadKeyPressAction(key=Key.L2))
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    # Go to connectivity category
    dispatch(KeypadKeyPressAction(key=Key.L1))
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    # Press the L1 key to open the wireless menu
    dispatch(KeypadKeyPressAction(key=Key.L1))
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    # Check list of current connections
    dispatch(KeypadKeyPressAction(key=Key.L2))
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    # Back
    dispatch(KeypadKeyPressAction(key=Key.BACK))
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    # Add new connection
    dispatch(KeypadKeyPressAction(key=Key.L1))
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    store_monitor.dispatched_actions.reset_mock()

    # Open camera to scan QR code
    dispatch(KeypadKeyPressAction(key=Key.L3))
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    @wait_for(stop=stop_after_delay(3))
    def camera_started() -> None:
        store_monitor.dispatched_actions.assert_any_call(
            CameraStartViewfinderAction(
                id=ANY,
                pattern=(
                    r'^WIFI:S:(?P<SSID>[^;]*);(?:T:(?P<Type>(?i:WEP|WPA|WPA2|nopass));)'
                    r'?(?:P:(?P<Password>[^;]*);)?(?:H:(?P<Hidden>(?i:true|false));)?;$'
                ),
            ),
        )

    camera_started()
