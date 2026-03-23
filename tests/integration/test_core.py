"""Test the general health of the application."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tenacity import stop_after_attempt, wait_fixed

if TYPE_CHECKING:
    from redux_pytest.fixtures import StoreSnapshot, WaitFor

    from tests.fixtures import AppContext
    from tests.fixtures.snapshot import WindowSnapshot
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

    @wait_for(run_async=True, stop=stop_after_attempt(5), wait=wait_fixed(1))
    def stack_is_loaded() -> None:
        from ubo_app.store.main import store

        state = store._state  # noqa: SLF001
        assert state is not None
        assert len(state.main.stack) > 0, 'Menu stack not loaded yet'

    await stack_is_loaded()

    await stability(initial_wait=30)

    from tests.conftest import exclude_dynamic_menus

    window_snapshot.take()
    store_snapshot.take(selector=exclude_dynamic_menus)
