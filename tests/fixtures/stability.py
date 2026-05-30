"""Fixtures for waiting for the stability of the screen and the store."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Protocol

import pytest

from tests.fixtures.snapshot import WindowSnapshot, write_png

if TYPE_CHECKING:
    from redux_pytest.fixtures import StoreSnapshot
    from redux_pytest.fixtures.wait_for import AsyncWaiter, WaitFor


class Stability(Protocol):
    """Fixture for waiting for the screen and store to stabilize."""

    async def __call__(
        self: Stability,
        initial_wait: float = 0,
        *,
        settle_polls: int = 6,
        poll_interval: float = 0.3,
        timeout: float = 30.0,  # noqa: ASYNC109
    ) -> AsyncWaiter:
        """Wait for the screen and store to stabilize.

        Polls the window hash and the store snapshot and returns as soon as
        the last ``settle_polls`` observations are identical (early exit).
        Raises after ``timeout`` seconds if the screen/store never settles.
        """
        ...


def _write_mismatch_diagnostics(
    *,
    store_snapshot: StoreSnapshot,
    window_snapshot: WindowSnapshot,
    store_snapshots: list[str],
    window_snapshots: list[bytes],
) -> None:
    """Persist the captured transient frames for post-mortem debugging."""
    for i, snapshot in enumerate(store_snapshots):
        (
            store_snapshot.results_dir
            / f'store-unstability_snapshot_{i}.mismatch.jsonc'
        ).write_text(snapshot)
    for i, snapshot in enumerate(window_snapshots):
        write_png(
            window_snapshot.results_dir
            / f'window-unstability_snapshot_{i}.mismatch.png',
            snapshot,
        )


@pytest.fixture
async def stability(
    store_snapshot: StoreSnapshot,
    window_snapshot: WindowSnapshot,
    wait_for: WaitFor,
) -> AsyncWaiter:
    """Wait for the screen and store to stabilize."""
    _ = wait_for

    async def wrapper(
        initial_wait: float = 0,
        *,
        settle_polls: int = 6,
        poll_interval: float = 0.3,
        timeout: float = 30.0,  # noqa: ASYNC109
    ) -> None:
        # ``initial_wait`` gives a dispatched action time to start rendering so
        # we don't sample a stale pre-render frame and mistake it for stable.
        if initial_wait:
            await asyncio.sleep(initial_wait)

        # Every distinct frame/state seen while unstable, kept for diagnostics
        # if we time out without settling.
        store_snapshots: list[str] = []
        window_snapshots: list[bytes] = []

        # Prime the first capture *before* starting the settle clock. The very
        # first screenshot of a freshly-booted app pays a one-time GUI
        # cold-boot latency (Kivy init + gRPC connect + first render) that is
        # unrelated to whether the screen has settled; charging it against
        # ``timeout`` would spuriously fail otherwise-fast tests on a cold GUI.
        previous_window = window_snapshot.hash
        assert previous_window, (
            'Window snapshot returned an empty hash — GUI is not responding'
        )
        previous_store = store_snapshot.json_snapshot()
        if window_snapshot._latest_data is not None:  # noqa: SLF001
            window_snapshots.append(window_snapshot._latest_data)  # noqa: SLF001
        store_snapshots.append(previous_store)

        # Ring buffers of the most recent observations; stable once the last
        # ``settle_polls`` window hashes and store snapshots are all identical.
        recent_window: list[str] = [previous_window]
        recent_store: list[str] = [previous_store]

        deadline = time.monotonic() + timeout

        while True:
            await asyncio.sleep(poll_interval)

            new_hash = window_snapshot.hash
            assert new_hash, (
                'Window snapshot returned an empty hash — GUI is not responding'
            )
            new_store = store_snapshot.json_snapshot()

            if new_hash != previous_window and window_snapshot._latest_data is not None:  # noqa: SLF001
                window_snapshots.append(window_snapshot._latest_data)  # noqa: SLF001
            if new_store != previous_store:
                store_snapshots.append(new_store)

            previous_window = new_hash
            previous_store = new_store

            recent_window.append(new_hash)
            recent_store.append(new_store)
            recent_window = recent_window[-settle_polls:]
            recent_store = recent_store[-settle_polls:]

            if (
                len(recent_window) >= settle_polls
                and len(set(recent_window)) == 1
                and len(set(recent_store)) == 1
            ):
                return

            if time.monotonic() >= deadline:
                _write_mismatch_diagnostics(
                    store_snapshot=store_snapshot,
                    window_snapshot=window_snapshot,
                    store_snapshots=store_snapshots,
                    window_snapshots=window_snapshots,
                )
                msg = (
                    f'Screen/store did not stabilize within {timeout}s '
                    f'(last {len(recent_window)} polls were not identical)'
                )
                raise AssertionError(msg)

    return wrapper
