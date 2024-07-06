"""Test the general health of the application."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tenacity import stop_after_attempt

if TYPE_CHECKING:
    from headless_kivy_pytest.fixtures import WindowSnapshot
    from redux_pytest.fixtures import StoreSnapshot, WaitFor

    from tests.fixtures import AppContext


async def test_app_runs_and_exits(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot,
    wait_for: WaitFor,
    needs_finish: None,
) -> None:
    """Test the application starts, runs and quits."""
    _ = needs_finish
    from ubo_app.menu_app.menu import MenuApp

    app = MenuApp()

    app_context.set_app(app)

    @wait_for(run_async=True, stop=stop_after_attempt(5))
    def stack_is_loaded() -> None:
        assert len(app.menu_widget.stack) > 0, 'Menu stack not loaded yet'

    await stack_is_loaded()

    from headless_kivy import HeadlessWidget, config

    @wait_for(run_async=True, stop=stop_after_attempt(5))
    def check() -> None:
        headless_widget_instance = HeadlessWidget.get_instance(app.root)
        if headless_widget_instance:
            assert (
                headless_widget_instance.fps == config.min_fps()
            ), 'Not in low fps mode'

    await check()

    window_snapshot.take()
    store_snapshot.take()
