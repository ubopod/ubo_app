"""Test the wireless flow."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
    from ubo_app.menu import MenuApp
    from ubo_app.store import RootState, dispatch, store
    from ubo_app.store.services.camera import CameraStartViewfinderAction
    from ubo_app.store.services.keypad import Key, KeypadKeyPressAction

    app = MenuApp()
    app_context.set_app(app)
    load_services(['wifi'])

    @wait_for
    def check_icon() -> None:
        state = store._state  # noqa: SLF001

        if not isinstance(state, RootState):
            return

        assert not any(
            icon.id == 'wifi:state' and icon.symbol == 'signal_wifi_off'
            for icon in state.status_icons.icons
        ), 'wifi icon not registered'

    check_icon()
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    dispatch(KeypadKeyPressAction(key=Key.L1))
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    dispatch(KeypadKeyPressAction(key=Key.L2))
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    dispatch(KeypadKeyPressAction(key=Key.L1))
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    dispatch(KeypadKeyPressAction(key=Key.L1))
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    dispatch(KeypadKeyPressAction(key=Key.L3))
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    @wait_for
    def camera_started() -> None:
        store_monitor.dispatched_actions.assert_called_with(
            CameraStartViewfinderAction(
                barcode_pattern=(
                    r'^WIFI:S:(?P<SSID>[^;]*);(?:T:(?P<Type>(?i:WEP|WPA|WPA2|nopass));)'
                    r'?(?:P:(?P<Password>[^;]*);)?(?:H:(?P<Hidden>(?i:true|false));)?$'
                ),
            ),
        )

    camera_started()
