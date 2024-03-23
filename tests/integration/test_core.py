"""Test the general health of the application."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redux_pytest.fixtures import StoreSnapshot, WaitFor

    from tests.fixtures import AppContext, WindowSnapshot


async def test_app_runs_and_exits(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot,
    needs_finish: None,
    wait_for: WaitFor,
) -> None:
    """Test the application starts, runs and quits."""
    _ = needs_finish
    from ubo_app.menu import MenuApp

    app = MenuApp()

    app_context.set_app(app)

    @wait_for(run_async=True)
    def stack_is_loaded() -> None:
        assert len(app.menu_widget.stack) > 0, 'Menu stack not loaded yet'

    await stack_is_loaded()

    from headless_kivy_pi import HeadlessWidget, config

    @wait_for(run_async=True)
    def check() -> None:
        headless_widget_instance = HeadlessWidget.get_instance(app.root)
        if headless_widget_instance:
            assert (
                headless_widget_instance.fps == config.min_fps()
            ), 'Not in low fps mode'

    await check()

    window_snapshot.take()
    store_snapshot.take()
