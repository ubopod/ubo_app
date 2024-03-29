"""Test the general health of the application."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest
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
    'notifications',
    'camera',
    'sensors',
    'docker',
    'ssh',
]


async def test_all_services_register(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot,
    needs_finish: None,
    load_services: LoadServices,
    stability: Stability,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test all services load."""
    _ = needs_finish
    from ubo_app.utils.fake import Fake

    class FakeProcess(Fake):
        returncode = 0

    monkeypatch.setattr(
        'asyncio.create_subprocess_exec',
        lambda *args, **kwargs: FakeProcess(args, kwargs),
    )
    from ubo_app.menu import MenuApp

    app = MenuApp()
    app_context.set_app(app)
    load_services(ALL_SERVICES_IDS)
    await stability()
    store_snapshot.take()
    window_snapshot.take()
