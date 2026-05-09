"""Tests for chunked file upload helper."""

from __future__ import annotations

from typing import Any

import pytest


class _FakeUploadClient:
    """Captures the FileUpload* dispatch sequence."""

    def __init__(self, *, fail_chunk: int | None = None, fail_times: int = 0) -> None:
        self.start_calls: list[dict[str, Any]] = []
        self.chunk_calls: list[dict[str, Any]] = []
        self.complete_calls: list[dict[str, Any]] = []
        # Inject failures for resilience tests: ``fail_chunk`` says which
        # chunk index should raise; ``fail_times`` how many attempts.
        self._fail_chunk = fail_chunk
        self._fail_times = fail_times
        self._fail_seen = 0

    def upload_file_start(self, **kwargs: Any) -> None:
        self.start_calls.append(kwargs)

    def upload_file_chunk(self, **kwargs: Any) -> None:
        if (
            self._fail_chunk is not None
            and kwargs["chunk_index"] == self._fail_chunk
            and self._fail_seen < self._fail_times
        ):
            self._fail_seen += 1
            msg = f"injected failure for chunk {self._fail_chunk}"
            raise RuntimeError(msg)
        self.chunk_calls.append(kwargs)

    def upload_file_complete(self, **kwargs: Any) -> None:
        self.complete_calls.append(kwargs)


@pytest.mark.asyncio
async def test_upload_dispatches_start_chunks_complete(tmp_path: Any) -> None:
    from ubo_tui.upload import CHUNK_SIZE, upload_file

    file_path = tmp_path / "big.bin"
    payload = b"A" * (CHUNK_SIZE + 100)  # 1 full chunk + 1 partial
    file_path.write_bytes(payload)

    client = _FakeUploadClient()
    await upload_file(client, "upload-1", file_path)

    assert len(client.start_calls) == 1
    start = client.start_calls[0]
    assert start["upload_id"] == "upload-1"
    assert start["filename"] == "big.bin"
    assert start["total_size"] == len(payload)
    assert start["total_chunks"] == 2
    assert start["chunk_size"] == CHUNK_SIZE

    assert [c["chunk_index"] for c in client.chunk_calls] == [0, 1]
    assert b"".join(c["data"] for c in client.chunk_calls) == payload

    assert client.complete_calls == [{"upload_id": "upload-1"}]


@pytest.mark.asyncio
async def test_upload_small_file_emits_single_chunk(tmp_path: Any) -> None:
    from ubo_tui.upload import upload_file

    file_path = tmp_path / "tiny.txt"
    file_path.write_bytes(b"hello")

    client = _FakeUploadClient()
    await upload_file(client, "upload-2", file_path)

    assert client.start_calls[0]["total_chunks"] == 1
    assert client.chunk_calls == [
        {"upload_id": "upload-2", "chunk_index": 0, "data": b"hello"},
    ]
    assert client.complete_calls == [{"upload_id": "upload-2"}]


@pytest.mark.asyncio
async def test_upload_retries_failed_chunk(tmp_path: Any, monkeypatch: Any) -> None:
    from ubo_tui import upload as upload_mod

    # Speed up retries so the test runs fast.
    monkeypatch.setattr(upload_mod, "RETRY_DELAY_SECONDS", 0)

    file_path = tmp_path / "data.bin"
    file_path.write_bytes(b"x" * 4)

    client = _FakeUploadClient(fail_chunk=0, fail_times=2)
    await upload_mod.upload_file(client, "upload-3", file_path)

    # Chunk 0 should ultimately succeed and appear once in chunk_calls.
    assert [c["chunk_index"] for c in client.chunk_calls] == [0]
    assert client.complete_calls == [{"upload_id": "upload-3"}]


@pytest.mark.asyncio
async def test_upload_progress_callback_invoked(tmp_path: Any) -> None:
    from ubo_tui.upload import CHUNK_SIZE, upload_file

    file_path = tmp_path / "big.bin"
    file_path.write_bytes(b"A" * (CHUNK_SIZE * 2 + 5))  # 3 chunks

    progress: list[tuple[int, int]] = []

    def _cb(sent: int, total: int) -> None:
        progress.append((sent, total))

    client = _FakeUploadClient()
    await upload_file(client, "upload-4", file_path, on_progress=_cb)

    assert progress == [(1, 3), (2, 3), (3, 3)]


@pytest.mark.asyncio
async def test_upload_chunk_failure_after_retries_raises(
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    from ubo_tui import upload as upload_mod

    monkeypatch.setattr(upload_mod, "RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(upload_mod, "MAX_RETRIES", 1)

    file_path = tmp_path / "data.bin"
    file_path.write_bytes(b"hello")

    client = _FakeUploadClient(fail_chunk=0, fail_times=99)

    with pytest.raises(RuntimeError):
        await upload_mod.upload_file(client, "upload-5", file_path)

    # Complete should NOT be dispatched on failure.
    assert client.complete_calls == []
