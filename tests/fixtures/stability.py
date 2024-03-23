"""Fixtures for waiting for the stability of the screen and the store."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

import pytest
from redux_pytest.fixtures.wait_for import AsyncWaiter, WaitFor

if TYPE_CHECKING:
    from redux_pytest.fixtures import StoreSnapshot

    from .snapshot import WindowSnapshot

Stability: TypeAlias = AsyncWaiter


@pytest.fixture()
async def stability(
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot,
    wait_for: WaitFor,
) -> AsyncWaiter:
    """Wait for the screen and store to stabilize."""

    async def wrapper() -> None:
        latest_window_hash = None
        latest_store_snapshot = None

        @wait_for(run_async=True)
        def check() -> None:
            nonlocal latest_window_hash, latest_store_snapshot

            new_hash = window_snapshot.hash
            new_snapshot = store_snapshot.json_snapshot

            is_window_stable = latest_window_hash == new_hash
            is_store_stable = latest_store_snapshot == new_snapshot

            latest_window_hash = new_hash
            latest_store_snapshot = new_snapshot

            assert is_window_stable, 'The content of the screen is not stable yet'
            assert is_store_stable, 'The content of the store is not stable yet'

        await check()

    return wrapper
