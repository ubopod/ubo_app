"""Test the general health of the application."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.conftest import AppContext


async def test_app_runs_and_exits(
    app_context: AppContext,
    needs_finish: None,
) -> None:
    """Test the application starts, runs and quits."""
    _ = needs_finish
    from ubo_app.menu import MenuApp

    app = MenuApp()

    app_context.set_app(app)
