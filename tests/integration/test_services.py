"""Test the general health of the application."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ubo_app.constants import CORE_SERVICE_IDS

if TYPE_CHECKING:
    from headless_kivy_pytest.fixtures import WindowSnapshot
    from redux_pytest.fixtures import StoreSnapshot

    from tests.fixtures import AppContext, LoadServices, Stability


@pytest.mark.timeout(80)
async def test_all_services_register(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot,
    load_services: LoadServices,
    stability: Stability,
) -> None:
    """Test all services load."""
    from ubo_app.menu_app.menu import MenuApp

    app = MenuApp()
    app_context.set_app(app)
    unload_waiter = await load_services(CORE_SERVICE_IDS, timeout=40, run_async=True)
    await stability(attempts=2, wait=2)
    store_snapshot.take()
    window_snapshot.take()
    app_context.dispatch_finish()
    await unload_waiter(timeout=30)
