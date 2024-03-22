"""Test the wireless flow."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pytest_mock import MockerFixture
    from redux.test import StoreSnapshotContext

    from tests.conftest import AppContext, LoadServices, Stability, WaitFor
    from tests.snapshot import WindowSnapshotContext


async def test_wireless_flow(
    app_context: AppContext,
    window_snapshot: WindowSnapshotContext,
    store_snapshot: StoreSnapshotContext,
    load_services: LoadServices,
    needs_finish: None,
    stability: Stability,
    mocker: MockerFixture,
    wait_for: WaitFor,
) -> None:
    """Test the wireless flow."""
    _ = needs_finish
    from ubo_app.menu import MenuApp
    from ubo_app.store import RootState, dispatch, store
    from ubo_app.store.services.camera import CameraStartViewfinderAction
    from ubo_app.store.services.keypad import Key, KeypadKeyPressAction

    app = MenuApp()
    app_context.set_app(app)
    await load_services(['wifi'])

    @wait_for
    def check_icon() -> None:
        state = store._state  # noqa: SLF001

        if not isinstance(state, RootState):
            return

        assert not any(
            icon.id == 'wifi:state' and icon.symbol == 'signal_wifi_off'
            for icon in state.status_icons.icons
        ), 'wifi icon not registered'

    await check_icon()
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

    monitor = mocker.stub()
    store.store_options = replace(store.store_options, action_middleware=monitor)
    dispatch(KeypadKeyPressAction(key=Key.L3))
    await stability()
    window_snapshot.take()
    store_snapshot.take()

    monitor.assert_called_with(
        CameraStartViewfinderAction(
            barcode_pattern=(
                r'WIFI:S:(?P<SSID>[^;]*);(?:T:(?P<Type>(?i:WEP|WPA|WPA2|nopass));)'
                r'?(?:P:(?P<Password>[^;]*);)?(?:H:(?P<Hidden>(?i:true|false));)?'
            ),
        ),
    )
