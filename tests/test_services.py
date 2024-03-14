# ruff: noqa: S101
"""Test the general health of the application."""
from __future__ import annotations

from typing import TYPE_CHECKING

from tenacity import AsyncRetrying, stop_after_delay, wait_fixed

if TYPE_CHECKING:
    from tests.conftest import AppContext
    from tests.snapshot import SnapshotContext

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
    snapshot: SnapshotContext,
    needs_finish: None,
) -> None:
    """Test all services load."""
    _ = needs_finish
    from ubo_app.load_services import load_services
    from ubo_app.menu import MenuApp

    app = MenuApp()
    load_services()
    app_context.set_app(app)

    latest_hash = snapshot.hash

    async for attempt in AsyncRetrying(
        stop=stop_after_delay(15),
        wait=wait_fixed(3),
    ):
        with attempt:
            from ubo_app.load_services import REGISTERED_PATHS

            for service_name in ALL_SERVICES_LABELS:
                assert any(
                    service.label == service_name and service.is_alive()
                    for service in REGISTERED_PATHS.values()
                ), f'{service_name} not loaded'
            is_stable = latest_hash == snapshot.hash
            latest_hash = snapshot.hash
            assert is_stable, 'Snapshot changed'

    snapshot.take()
