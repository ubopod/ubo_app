# ruff: noqa: S101
"""Test the general health of the application."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from redux import FinishAction

if TYPE_CHECKING:
    from tests.conftest import AppContext


async def test_app_runs_and_exits(
    app_context: AppContext,
    needs_finish: None,
) -> None:
    """Test the application starts, runs and quits."""
    _ = needs_finish
    from ubo_app.menu import MenuApp
    from ubo_app.store import dispatch

    app = MenuApp()
    app_context.set_app(app)
    dispatch(FinishAction())

    await asyncio.sleep(1)
