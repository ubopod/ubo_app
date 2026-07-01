"""Regression tests for the chunked-upload waiter's failure paths.

``await_completed_upload`` is awaited by the wake-word model upload flow after the
input dialog closes. If the web client dies mid-upload (a start/chunk/complete
dispatch throws client-side and is only logged), the server never registers a
completion or failure, so without a timeout the waiter blocks forever. These tests
pin the two ways the await must terminate: a bounded timeout, and an explicit
``register_failed_upload``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ubo_app.utils.file_upload import (
    _DEFAULT_UPLOAD_TIMEOUT,
    _upload_timeout,
    await_completed_upload,
    register_completed_upload,
    register_failed_upload,
)

if TYPE_CHECKING:
    from pathlib import Path


async def test_await_times_out_when_never_completed() -> None:
    """A never-completed upload raises (does not hang) once the timeout elapses."""
    with pytest.raises(RuntimeError):
        await await_completed_upload('never-completes', timeout=0.05)


async def test_await_raises_on_registered_failure() -> None:
    """A registered failure wakes the waiter with the failure reason."""

    async def fail_soon() -> None:
        await asyncio.sleep(0.01)
        register_failed_upload('will-fail', 'boom')

    task = asyncio.create_task(fail_soon())
    with pytest.raises(RuntimeError, match='boom'):
        await await_completed_upload('will-fail', timeout=1)
    await task


def test_upload_timeout_falls_back_on_malformed_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed ``UBO_UPLOAD_TIMEOUT`` falls back instead of raising."""
    monkeypatch.setenv('UBO_UPLOAD_TIMEOUT', 'not-a-number')
    assert _upload_timeout() == _DEFAULT_UPLOAD_TIMEOUT


def test_upload_timeout_reads_valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid ``UBO_UPLOAD_TIMEOUT`` overrides the default."""
    monkeypatch.setenv('UBO_UPLOAD_TIMEOUT', '7.5')
    assert _upload_timeout() == 7.5


async def test_await_returns_bytes_when_already_completed(tmp_path: Path) -> None:
    """The already-completed fast path returns the file bytes and unlinks it."""
    temp_file = tmp_path / 'upload.bin'
    temp_file.write_bytes(b'payload')
    register_completed_upload('already-done', str(temp_file))

    data = await await_completed_upload('already-done', timeout=1)

    assert data == b'payload'
    assert not temp_file.exists()
