"""Test the general health of the application."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tenacity import RetryError

if TYPE_CHECKING:
    from redux_pytest.fixtures import StoreSnapshot

    from tests.fixtures import AppContext, LoadServices, Stability, WindowSnapshot

ALL_SERVICES_IDS = [
    'rgb_ring',
    'sound',
    'ethernet',
    'ip',
    'wifi',
    'keyboard',
    'keypad',
    'lightdm',
    'notifications',
    'camera',
    'sensors',
    'docker',
    'ssh',
    'voice',
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
    load_services(ALL_SERVICES_IDS, timeout=10)
    for _ in range(3):
        try:
            await asyncio.sleep(3)
            await stability(timeout=3)
            store_snapshot.take()
            window_snapshot.take()
            break
        except RetryError as exception:
            if isinstance(exception.last_attempt.exception(), AssertionError):
                continue
            raise
        except AssertionError:
            continue
    else:
        store_snapshot.take()
        window_snapshot.take()
