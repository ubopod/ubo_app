"""Test the general health of the application."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tenacity import stop_after_attempt

if TYPE_CHECKING:
    from headless_kivy_pytest.fixtures import WindowSnapshot
    from redux_pytest.fixtures import StoreSnapshot, WaitFor

    from tests.fixtures import AppContext
    from tests.fixtures.stability import Stability


async def test_app_runs_and_exits(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot,
    wait_for: WaitFor,
    stability: Stability,
) -> None:
    """Test the application starts, runs and quits."""
    app_context.set_app()

    @wait_for(run_async=True, stop=stop_after_attempt(5))
    def stack_is_loaded() -> None:
        assert len(app_context.app.menu_widget.stack) > 0, 'Menu stack not loaded yet'

    await stack_is_loaded()

    await stability()

    window_snapshot.take()
    store_snapshot.take()
