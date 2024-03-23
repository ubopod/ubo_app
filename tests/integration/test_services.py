"""Test the general health of the application."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redux_pytest.fixtures import StoreSnapshot

    from tests.fixtures import AppContext, LoadServices, Stability, WindowSnapshot

ALL_SERVICES_LABELS = [
    'rgb_ring',
    'sound',
    'ethernet',
    'ip',
    'wifi',
    'keyboard',
    'keypad',
    'notifications',
    'camera',
    'sensors',
    'docker',
]


async def test_all_services_register(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot,
    needs_finish: None,
    load_services: LoadServices,
    stability: Stability,
) -> None:
    """Test all services load."""
    _ = needs_finish
    from ubo_app.menu import MenuApp

    app = MenuApp()
    app_context.set_app(app)
    load_services(ALL_SERVICES_LABELS)
    await stability()
    store_snapshot.take()
    window_snapshot.take()
