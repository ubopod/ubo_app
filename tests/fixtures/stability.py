"""Fixtures for waiting for the stability of the screen and the store."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import pytest
from tenacity import RetryError, stop_after_delay, wait_fixed

from tests.fixtures.snapshot import write_image

if TYPE_CHECKING:
    from redux_pytest.fixtures import StoreSnapshot
    from redux_pytest.fixtures.wait_for import AsyncWaiter, WaitFor

    from .snapshot import WindowSnapshot


class Stability(Protocol):
    """Fixture for waiting for the screen and store to stabilize."""

    async def __call__(
        self: Stability,
        timeout: float | None = None,
    ) -> AsyncWaiter:
        """Wait for the screen and store to stabilize."""
        ...


@pytest.fixture()
async def stability(
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot,
    wait_for: WaitFor,
) -> AsyncWaiter:
    """Wait for the screen and store to stabilize."""

    async def wrapper(
        timeout: float | None = None,
    ) -> None:
        latest_window_hash = None
        latest_store_snapshot = None

        snapshots = []

        @wait_for(
            run_async=True,
            wait=wait_fixed(1),
            stop=stop_after_delay(timeout or 4),
        )
        def check() -> None:
            nonlocal latest_window_hash, latest_store_snapshot

            new_hash = window_snapshot.hash
            new_snapshot = store_snapshot.json_snapshot

            is_window_stable = latest_window_hash == new_hash
            is_store_stable = latest_store_snapshot == new_snapshot

            latest_window_hash = new_hash
            latest_store_snapshot = new_snapshot

            if not is_window_stable:
                from headless_kivy_pi.config import _display

                snapshots.append(_display.raw_data.copy())

            assert is_window_stable, 'The content of the screen is not stable yet'
            assert is_store_stable, 'The content of the store is not stable yet'

        try:
            await check()
        except RetryError:
            for i, snapshot in enumerate(snapshots):
                write_image(
                    window_snapshot.results_dir
                    / f'window-unstability_snapshot_{i}.mismatch.png',
                    snapshot,
                )
            raise

    return wrapper
