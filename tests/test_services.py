"""Test the general health of the application."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tenacity import AsyncRetrying, stop_after_delay, wait_fixed

if TYPE_CHECKING:
    from redux.test import StoreSnapshotContext

    from tests.conftest import AppContext
    from tests.snapshot import WindowSnapshotContext

ALL_SERVICES_LABELS = [
    'RGB Ring',
    'Sound',
    'Ethernet',
    'IP',
    'WiFi',
    'Keyboard',
    'Keypad',
    'Notifications',
    'Camera',
    'Sensors',
    'Docker',
]


async def test_all_services_register(
    app_context: AppContext,
    window_snapshot: WindowSnapshotContext,
    store_snapshot: StoreSnapshotContext,
    needs_finish: None,
) -> None:
    """Test all services load."""
    _ = needs_finish
    from ubo_app.load_services import load_services
    from ubo_app.menu import MenuApp

    app = MenuApp()
    app_context.set_app(app)
    load_services()

    latest_window_hash = window_snapshot.hash
    latest_store_snapshot = store_snapshot.json_snapshot

    async for attempt in AsyncRetrying(stop=stop_after_delay(80), wait=wait_fixed(5)):
        with attempt:
            from ubo_app.load_services import REGISTERED_PATHS

            for service_name in ALL_SERVICES_LABELS:
                assert any(
                    service.label == service_name and service.is_alive()
                    for service in REGISTERED_PATHS.values()
                ), f'{service_name} not loaded'

            new_hash = window_snapshot.hash
            new_snapshot = store_snapshot.json_snapshot

            is_window_stable = latest_window_hash == new_hash
            is_store_stable = latest_store_snapshot == new_snapshot

            latest_window_hash = new_hash
            latest_store_snapshot = new_snapshot

            assert is_window_stable, 'The content of the screen is not stable yet'
            assert is_store_stable, 'The content of the store is not stable yet'

    window_snapshot.take()
    store_snapshot.take()
