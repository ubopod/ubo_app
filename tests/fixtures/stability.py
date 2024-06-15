"""Fixtures for waiting for the stability of the screen and the store."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol

import pytest
from tenacity import RetryError, stop_after_delay, wait_fixed

from tests.fixtures.snapshot import write_image

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from numpy._typing import NDArray
    from redux_pytest.fixtures import StoreSnapshot
    from redux_pytest.fixtures.wait_for import AsyncWaiter, WaitFor

    from tests.fixtures.app import AppContext

    from .snapshot import WindowSnapshot


class Stability(Protocol):
    """Fixture for waiting for the screen and store to stabilize."""

    async def __call__(
        self: Stability,
        timeout: float = 5,
        initial_wait: float = 0.2,
        attempts: int = 1,
        wait: float = 0.5,
    ) -> AsyncWaiter:
        """Wait for the screen and store to stabilize."""
        ...


async def _run(
    *,
    initial_wait: float,
    attempts: int,
    wait: float,
    check: Callable[[], Coroutine],
    store_snapshot: StoreSnapshot,
    window_snapshot: WindowSnapshot,
    store_snapshots: list[str],
    window_snapshots: list[NDArray],
) -> None:
    await asyncio.sleep(initial_wait)
    for _ in range(attempts):
        try:
            await check()
            await asyncio.sleep(wait)
        except RetryError as exception:
            if isinstance(exception.last_attempt.exception(), AssertionError):
                continue
            raise
        except AssertionError:
            continue

    try:
        await check()
    except RetryError:
        for i, snapshot in enumerate(store_snapshots):
            (
                store_snapshot.results_dir
                / f'store-unstability_snapshot_{i}.mismatch.jsonc'
            ).write_text(snapshot)
        for i, snapshot in enumerate(window_snapshots):
            write_image(
                window_snapshot.results_dir
                / f'window-unstability_snapshot_{i}.mismatch.png',
                snapshot,
            )
        raise


@pytest.fixture()
async def stability(
    store_snapshot: StoreSnapshot,
    window_snapshot: WindowSnapshot,
    wait_for: WaitFor,
    app_context: AppContext,
) -> AsyncWaiter:
    """Wait for the screen and store to stabilize."""

    async def wrapper(
        timeout: float = 5,
        initial_wait: float = 0.2,
        attempts: int = 1,
        wait: float = 0.5,
    ) -> None:
        latest_window_hash = None
        latest_store_snapshot = None

        store_snapshots = []
        window_snapshots = []

        @wait_for(
            run_async=True,
            wait=wait_fixed(wait),
            stop=stop_after_delay(timeout),
        )
        def check() -> None:
            nonlocal latest_window_hash, latest_store_snapshot

            new_hash = window_snapshot.hash
            new_snapshot = store_snapshot.json_snapshot()

            is_window_stable = latest_window_hash == new_hash
            is_store_stable = latest_store_snapshot == new_snapshot

            latest_window_hash = new_hash
            latest_store_snapshot = new_snapshot

            if not is_window_stable:
                from headless_kivy_pi.config import _display

                window_snapshots.append(_display.raw_data.copy())

            if not is_store_stable:
                store_snapshots.append(store_snapshot.json_snapshot())

            assert is_window_stable, 'The content of the screen is not stable yet'
            assert is_store_stable, 'The content of the store is not stable yet'

            from headless_kivy_pi import HeadlessWidget, config

            headless_widget_instance = HeadlessWidget.get_instance(app_context.app.root)
            if headless_widget_instance:
                assert (
                    headless_widget_instance.fps == config.min_fps()
                ), 'Not in low fps mode'

        await _run(
            initial_wait=initial_wait,
            attempts=attempts,
            wait=wait,
            check=check,
            store_snapshot=store_snapshot,
            window_snapshot=window_snapshot,
            store_snapshots=store_snapshots,
            window_snapshots=window_snapshots,
        )

    return wrapper
