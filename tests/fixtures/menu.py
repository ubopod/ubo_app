"""Menu-related fixtures and utilities."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, overload

import pytest
from tenacity import wait_fixed

if TYPE_CHECKING:
    from _pytest.fixtures import SubRequest  # pyright: ignore[reportPrivateImportUsage]
    from redux_pytest.fixtures import WaitFor

    from tests.fixtures.snapshot import WindowSnapshot


def _get_window_snapshot(request: SubRequest) -> WindowSnapshot | None:
    """Try to get the window_snapshot fixture if available in the test."""
    try:
        return request.getfixturevalue('window_snapshot')
    except pytest.FixtureLookupError:
        return None


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
    wait_for: WaitFor,
    request: SubRequest,
) -> WaitForMenuItem:
    """Wait for a menu item to show up in both Redux state and rendered GUI."""
    snapshot = _get_window_snapshot(request)

    async def wait_for_menu_item(
        *,
        label: str | None = None,
        icon: str | None = None,
    ) -> None:
        # Capture the hash before the action so we can verify the GUI changed
        hash_before_action = snapshot.hash if snapshot is not None else None

        @wait_for(wait=wait_fixed(0.5), run_async=True)
        def check() -> None:
            from ubo_app.store.core.types import HomeViewData, MenuViewData
            from ubo_app.store.main import store

            state = store._state  # noqa: SLF001
            assert state is not None
            current_view = state.main.current_view
            assert current_view is not None

            if isinstance(current_view, MenuViewData):
                items = current_view.items
            elif isinstance(current_view, HomeViewData):
                items = current_view.menu_items
            else:
                msg = f'Current view is not a menu view: {type(current_view)}'
                raise TypeError(msg)

            if label is not None:
                assert any(item and item.label == label for item in items)
            if icon is not None:
                assert any(item and item.icon == icon for item in items)

            # When a GUI is available, also verify the rendered output changed
            # from before the action was dispatched. This catches "stable wrong
            # render" scenarios where the store is correct but the GUI never
            # re-rendered.
            if snapshot is not None and hash_before_action is not None:
                current_hash = snapshot.hash
                assert current_hash != hash_before_action, (
                    'GUI window hash did not change — the menu item may be in '
                    'the store but the GUI has not re-rendered'
                )

        await check()

        # Verify the GUI is stable (no more re-renders in flight)
        if snapshot is not None:
            hash_after = snapshot.hash
            await asyncio.sleep(1)
            hash_settled = snapshot.hash
            assert hash_after == hash_settled, (
                'Window snapshot is not stable after menu item appeared'
            )
        else:
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
def wait_for_empty_menu(
    wait_for: WaitFor,
    request: SubRequest,
) -> WaitForEmptyMenu:
    """Wait for the placeholder to show up in both Redux state and rendered GUI."""
    snapshot = _get_window_snapshot(request)

    async def wait_for_empty_menu(
        *,
        placeholder: str | None = None,
    ) -> None:
        # Capture the hash before the action so we can verify the GUI changed
        hash_before_action = snapshot.hash if snapshot is not None else None

        @wait_for(wait=wait_fixed(0.5), run_async=True)
        def check() -> None:
            from ubo_app.store.core.types import MenuViewData
            from ubo_app.store.main import store

            state = store._state  # noqa: SLF001
            assert state is not None
            current_view = state.main.current_view
            assert current_view is not None

            assert isinstance(current_view, MenuViewData)
            assert all(item is None for item in current_view.items)
            if placeholder is not None:
                assert current_view.placeholder == placeholder

            # When a GUI is available, also verify the rendered output changed
            if snapshot is not None and hash_before_action is not None:
                current_hash = snapshot.hash
                assert current_hash != hash_before_action, (
                    'GUI window hash did not change — the empty menu may be in '
                    'the store but the GUI has not re-rendered'
                )

        await check()

        # Verify the GUI is stable (no more re-renders in flight)
        if snapshot is not None:
            hash_after = snapshot.hash
            await asyncio.sleep(1)
            hash_settled = snapshot.hash
            assert hash_after == hash_settled, (
                'Window snapshot is not stable after empty menu appeared'
            )
        else:
            await asyncio.sleep(1)

    return wait_for_empty_menu
