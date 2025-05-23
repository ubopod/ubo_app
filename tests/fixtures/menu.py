"""Menu-related fixtures and utilities."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, overload

import pytest
from tenacity import wait_fixed

if TYPE_CHECKING:
    from collections.abc import Sequence

    from redux_pytest.fixtures import WaitFor
    from ubo_gui.menu.types import Item

    from .app import AppContext


class WaitForMenuItem(Protocol):
    """Wait for a menu item to show up."""

    @overload
    async def __call__(
        self: WaitForMenuItem,
        *,
        label: str,
        icon: str | None = None,
    ) -> None: ...
    @overload
    async def __call__(
        self: WaitForMenuItem,
        *,
        icon: str,
    ) -> None: ...


@pytest.fixture
def wait_for_menu_item(
    app_context: AppContext,
    wait_for: WaitFor,
) -> WaitForMenuItem:
    """Wait for a menu item to show up."""

    async def wait_for_menu_item(
        *,
        label: str | None = None,
        icon: str | None = None,
    ) -> None:
        @wait_for(wait=wait_fixed(0.5), run_async=True)
        def check() -> None:
            from ubo_gui.page import PageWidget

            assert app_context.app.menu_widget._running_transition_end_time is None  # noqa: SLF001
            current_page = app_context.app.menu_widget.current_screen
            assert current_page is not None
            if not isinstance(current_page, PageWidget):
                msg = 'Current page is not a StackMenuItem'
                raise TypeError(msg)
            if current_page.items is None:
                msg = 'No items in current page'
                raise TypeError(msg)
            items: Sequence[Item | None] = current_page.items
            if label is not None:
                assert any(item and item.label == label for item in items)
            if icon is not None:
                assert any(item and item.icon == icon for item in items)

        await check()
        await asyncio.sleep(1)

    return wait_for_menu_item


class WaitForEmptyMenu(Protocol):
    """Wait for the placeholder to show up."""

    async def __call__(
        self: WaitForEmptyMenu,
        *,
        placeholder: str | None = None,
    ) -> None:
        """Wait for the placeholder to show up."""


@pytest.fixture
def wait_for_empty_menu(app_context: AppContext, wait_for: WaitFor) -> WaitForEmptyMenu:
    """Wait for the placeholder to show up."""

    async def wait_for_empty_menu(
        *,
        placeholder: str | None = None,
    ) -> None:
        @wait_for(wait=wait_fixed(0.5), run_async=True)
        def check() -> None:
            assert app_context.app.menu_widget._running_transition_end_time is None  # noqa: SLF001
            current_page = app_context.app.menu_widget.current_screen
            assert current_page is not None

            from ubo_gui.page import PageWidget

            assert isinstance(current_page, PageWidget)
            assert all(item is None for item in current_page.items)
            if placeholder is not None:
                assert current_page.placeholder == placeholder

        await check()
        await asyncio.sleep(1)

    return wait_for_empty_menu
