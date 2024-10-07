"""Test the general health of the application."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from headless_kivy_pytest.fixtures import WindowSnapshot
    from redux_pytest.fixtures import StoreSnapshot

    from tests.fixtures import AppContext, LoadServices, Stability

ALL_SERVICES_IDS = [
    'audio',
    'camera',
    'display',
    'docker',
    'ethernet',
    'ip',
    'keyboard',
    'keypad',
    'lightdm',
    'notifications',
    'rgb_ring',
    'rpi_connect',
    'sensors',
    'ssh',
    'users',
    'voice',
    'vscode',
    'web_ui',
    'wifi',
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
    from ubo_app.menu_app.menu import MenuApp

    app = MenuApp()
    app_context.set_app(app)
    load_services(ALL_SERVICES_IDS, timeout=15, delay=0.7)
    await stability(initial_wait=6, attempts=2, wait=2)
    store_snapshot.take()
    window_snapshot.take()
