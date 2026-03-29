"""Menu-related fixtures and utilities."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, overload

import pytest
from tenacity import wait_fixed

from tests.fixtures.snapshot import write_png

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


def _debug_store_status() -> str:
    """Return a short debug string with current view type and status icons."""
    from ubo_app.store.main import store

    state = store._state  # noqa: SLF001
    if state is None:
        return 'store=None'

    current_view = state.main.current_view
    view_type = type(current_view).__name__ if current_view else 'None'
    icons = [(i.id, i.symbol) for i in state.status_icons.icons]
    return f'view={view_type} icons={icons}'


async def _wait_for_gui_settle(
    snapshot: WindowSnapshot | None,
    *,
    initial_hash: str | None = None,
    max_attempts: int = 5,
    context: str = 'menu item',
    require_hash_change: bool = True,
) -> None:
    """Wait until two consecutive GUI hashes match, or raise after max_attempts."""
    from ubo_app.logger import logger

    if snapshot is None:
        await asyncio.sleep(1)
        return

    # Keep the last two screenshots for debugging on failure
    prev_data: bytes | None = None
    curr_data: bytes | None = None

    for attempt in range(max_attempts):
        hash_after = snapshot.hash
        prev_data = snapshot._latest_data  # noqa: SLF001
        store_info = _debug_store_status()
        await asyncio.sleep(1)
        hash_settled = snapshot.hash
        curr_data = snapshot._latest_data  # noqa: SLF001
        store_info_after = _debug_store_status()
        if hash_after == hash_settled:
            if (
                require_hash_change
                and initial_hash is not None
                and hash_settled == initial_hash
            ):
                msg = (
                    'GUI window hash did not change after action — the menu item may '
                    'be in the store but the GUI has not re-rendered'
                )
                raise AssertionError(msg)
            logger.info(
                '[settle] %s: stable after attempt %d hash=%s… %s',
                context,
                attempt + 1,
                hash_after[:12],
                store_info,
            )
            return
        logger.warning(
            '[settle] %s: UNSTABLE attempt %d/%d '
            'hash %s…→%s… before=(%s) after=(%s)',
            context,
            attempt + 1,
            max_attempts,
            hash_after[:12],
            hash_settled[:12],
            store_info,
            store_info_after,
        )

    # Save the last two unstable screenshots for visual inspection
    results_dir = snapshot.results_dir
    if prev_data is not None:
        write_png(
            results_dir / f'settle-unstable-{context}-before.mismatch.png',
            prev_data,
        )
    if curr_data is not None:
        write_png(
            results_dir / f'settle-unstable-{context}-after.mismatch.png',
            curr_data,
        )

    msg = (
        f'Window snapshot is not stable after {context} appeared '
        f'({max_attempts} attempts). '
        f'Saved screenshots to {results_dir}/settle-unstable-*'
    )
    raise AssertionError(msg)


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
        hash_before_wait = snapshot.hash if snapshot is not None else None
        require_hash_change = True

        @wait_for(wait=wait_fixed(0.5), run_async=True)
        def check() -> None:
            from ubo_app.store.core.types import (
                HomeViewData,
                MenuViewData,
                NotificationViewData,
            )
            from ubo_app.store.main import store

            state = store._state  # noqa: SLF001
            assert state is not None
            current_view = state.main.current_view
            assert current_view is not None

            nonlocal require_hash_change
            if isinstance(current_view, MenuViewData | NotificationViewData):
                items = current_view.items
                # Notifications can already be fully rendered by the time the
                # test starts waiting for their dismiss action, so requiring a
                # post-wait hash change is too strict here.
                require_hash_change = not isinstance(
                    current_view,
                    NotificationViewData,
                )
            elif isinstance(current_view, HomeViewData):
                items = current_view.menu_items
            else:
                msg = f'Current view is not a menu view: {type(current_view)}'
                raise TypeError(msg)

            if label is not None:
                assert any(item and item.label == label for item in items)
            if icon is not None:
                assert any(item and item.icon == icon for item in items)

        await check()
        await _wait_for_gui_settle(
            snapshot,
            initial_hash=hash_before_wait,
            context='menu item',
            require_hash_change=require_hash_change,
        )

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
        hash_before_wait = snapshot.hash if snapshot is not None else None

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

        await check()
        await _wait_for_gui_settle(
            snapshot,
            initial_hash=hash_before_wait,
            context='empty menu',
            require_hash_change=False,
        )

    return wait_for_empty_menu
