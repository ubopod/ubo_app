"""Tests for chunked file upload: reducer pass-through and server-side assembly.

NOTE: The file system service uses relative imports (from constants import ...,
from file_application import ...). We add the service directory to sys.path
before importing the reducer.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

import pytest
from redux import CompleteReducerResult, InitAction

from ubo_app.store.services.file_system import FileSystemState


def _import_store_types_and_reducer() -> tuple:
    """Import store types and the file system reducer.

    Records sys.modules before import and cleans up ALL newly loaded modules
    afterwards so that integration/flow tests that rely on fresh store
    initialization are not affected by leftover module state.
    """
    modules_before = set(sys.modules)

    from ubo_app.store.services.file_upload import (
        FileUploadChunkAction,
        FileUploadChunkEvent,
        FileUploadCompleteAction,
        FileUploadCompleteEvent,
        FileUploadStartAction,
        FileUploadStartEvent,
    )

    # Add the service directory to sys.path so relative imports work
    service_dir = str(
        Path(__file__).resolve().parents[2]
        / 'ubo_app'
        / 'services'
        / '090-file-system',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    from reducer import reducer  # pyright: ignore[reportMissingImports]

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return (
        FileUploadChunkAction,
        FileUploadChunkEvent,
        FileUploadCompleteAction,
        FileUploadCompleteEvent,
        FileUploadStartAction,
        FileUploadStartEvent,
        reducer,
    )


(
    FileUploadChunkAction,
    FileUploadChunkEvent,
    FileUploadCompleteAction,
    FileUploadCompleteEvent,
    FileUploadStartAction,
    FileUploadStartEvent,
    reducer,
) = _import_store_types_and_reducer()


def _init_state() -> FileSystemState:
    """Initialize a fresh FileSystemState via the reducer."""
    result = reducer(None, InitAction())
    assert isinstance(result, FileSystemState)
    return result


CHUNK_SIZE = 1024
UPLOAD_ID = 'test-upload-001'


class TestFileUploadReducer:
    """Tests for reducer pass-through of file upload actions."""

    def test_start_action_emits_start_event(self) -> None:
        """FileUploadStartAction emits FileUploadStartEvent with correct fields."""
        state = _init_state()
        result = reducer(
            state,
            FileUploadStartAction(
                upload_id=UPLOAD_ID,
                target_directory='/tmp/uploads',  # noqa: S108
                filename='test.bin',
                total_size=3072,
                total_chunks=3,
                chunk_size=CHUNK_SIZE,
            ),
        )
        assert isinstance(result, CompleteReducerResult)
        assert result.events is not None

        events = [e for e in result.events if isinstance(e, FileUploadStartEvent)]
        assert len(events) == 1
        event = events[0]
        assert event.upload_id == UPLOAD_ID
        assert event.target_directory == '/tmp/uploads'  # noqa: S108
        assert event.filename == 'test.bin'
        assert event.total_size == 3072
        assert event.total_chunks == 3
        assert event.chunk_size == CHUNK_SIZE

    def test_start_action_preserves_state(self) -> None:
        """FileUploadStartAction does not modify state."""
        state = _init_state()
        result = reducer(
            state,
            FileUploadStartAction(
                upload_id=UPLOAD_ID,
                target_directory='/tmp/uploads',  # noqa: S108
                filename='test.bin',
                total_size=3072,
                total_chunks=3,
                chunk_size=CHUNK_SIZE,
            ),
        )
        assert isinstance(result, CompleteReducerResult)
        assert result.state is state

    def test_chunk_action_emits_chunk_event(self) -> None:
        """FileUploadChunkAction emits FileUploadChunkEvent with data intact."""
        state = _init_state()
        chunk_data = b'\x00\x01\x02\x03' * 256
        result = reducer(
            state,
            FileUploadChunkAction(
                upload_id=UPLOAD_ID,
                chunk_index=0,
                data=chunk_data,
            ),
        )
        assert isinstance(result, CompleteReducerResult)
        assert result.events is not None

        events = [e for e in result.events if isinstance(e, FileUploadChunkEvent)]
        assert len(events) == 1
        assert events[0].upload_id == UPLOAD_ID
        assert events[0].chunk_index == 0
        assert events[0].data == chunk_data

    def test_complete_action_emits_complete_event(self) -> None:
        """FileUploadCompleteAction emits FileUploadCompleteEvent."""
        state = _init_state()
        result = reducer(
            state,
            FileUploadCompleteAction(upload_id=UPLOAD_ID),
        )
        assert isinstance(result, CompleteReducerResult)
        assert result.events is not None

        events = [e for e in result.events if isinstance(e, FileUploadCompleteEvent)]
        assert len(events) == 1
        assert events[0].upload_id == UPLOAD_ID


class TestUploadHandlerAssembly:
    """Tests for server-side file assembly via upload_handler."""

    def test_end_to_end_file_assembly_hash_match(self) -> None:
        """Chunks out of order assemble to match source hash."""
        from unittest.mock import patch

        from upload_handler import (  # pyright: ignore[reportMissingImports]
            _sessions,
            handle_upload_chunk,
            handle_upload_complete,
            handle_upload_start,
        )

        # Generate random content: 3 full chunks
        chunk_size = 1024
        num_chunks = 3
        total_size = chunk_size * num_chunks
        source_data = os.urandom(total_size)
        source_hash = hashlib.sha256(source_data).hexdigest()

        # Split into chunks
        chunks = [
            source_data[i * chunk_size : (i + 1) * chunk_size]
            for i in range(num_chunks)
        ]

        target_dir = tempfile.mkdtemp()
        upload_id = 'test-assembly'

        try:
            with patch('upload_handler.store'):
                handle_upload_start(
                    FileUploadStartEvent(
                        upload_id=upload_id,
                        target_directory=target_dir,
                        filename='assembled.bin',
                        total_size=total_size,
                        total_chunks=num_chunks,
                        chunk_size=chunk_size,
                    ),
                )

                # Send chunks OUT OF ORDER: 2, 0, 1
                for idx in [2, 0, 1]:
                    handle_upload_chunk(
                        FileUploadChunkEvent(
                            upload_id=upload_id,
                            chunk_index=idx,
                            data=chunks[idx],
                        ),
                    )

                handle_upload_complete(
                    FileUploadCompleteEvent(upload_id=upload_id),
                )

            # Verify assembled file
            assembled = Path(target_dir) / 'assembled.bin'
            assert assembled.exists()
            assembled_hash = hashlib.sha256(assembled.read_bytes()).hexdigest()
            assert assembled_hash == source_hash
        finally:
            # Cleanup
            import shutil

            shutil.rmtree(target_dir, ignore_errors=True)
            _sessions.pop(upload_id, None)

    def test_end_to_end_with_partial_last_chunk(self) -> None:
        """File with a partial last chunk is assembled correctly."""
        from unittest.mock import patch

        from upload_handler import (  # pyright: ignore[reportMissingImports]
            _sessions,
            handle_upload_chunk,
            handle_upload_complete,
            handle_upload_start,
        )

        chunk_size = 1024
        # 2.5 chunks worth of data
        total_size = chunk_size * 2 + 512
        num_chunks = 3
        source_data = os.urandom(total_size)
        source_hash = hashlib.sha256(source_data).hexdigest()

        chunks = []
        for i in range(num_chunks):
            start = i * chunk_size
            end = min(start + chunk_size, total_size)
            chunks.append(source_data[start:end])

        target_dir = tempfile.mkdtemp()
        upload_id = 'test-partial'

        try:
            with patch('upload_handler.store'):
                handle_upload_start(
                    FileUploadStartEvent(
                        upload_id=upload_id,
                        target_directory=target_dir,
                        filename='partial.bin',
                        total_size=total_size,
                        total_chunks=num_chunks,
                        chunk_size=chunk_size,
                    ),
                )

                for idx in range(num_chunks):
                    handle_upload_chunk(
                        FileUploadChunkEvent(
                            upload_id=upload_id,
                            chunk_index=idx,
                            data=chunks[idx],
                        ),
                    )

                handle_upload_complete(
                    FileUploadCompleteEvent(upload_id=upload_id),
                )

            assembled = Path(target_dir) / 'partial.bin'
            assert assembled.exists()
            assembled_hash = hashlib.sha256(assembled.read_bytes()).hexdigest()
            assert assembled_hash == source_hash
        finally:
            import shutil

            shutil.rmtree(target_dir, ignore_errors=True)
            _sessions.pop(upload_id, None)

    def test_path_traversal_prevention(self) -> None:
        """Filename with path traversal components uses only the basename."""
        from unittest.mock import patch

        from upload_handler import (  # pyright: ignore[reportMissingImports]
            _sessions,
            handle_upload_chunk,
            handle_upload_complete,
            handle_upload_start,
        )

        chunk_size = 64
        data = b'safe content here'
        total_size = len(data)

        target_dir = tempfile.mkdtemp()
        upload_id = 'test-traversal'

        try:
            with patch('upload_handler.store'):
                handle_upload_start(
                    FileUploadStartEvent(
                        upload_id=upload_id,
                        target_directory=target_dir,
                        filename='../../etc/passwd',
                        total_size=total_size,
                        total_chunks=1,
                        chunk_size=chunk_size,
                    ),
                )

                handle_upload_chunk(
                    FileUploadChunkEvent(
                        upload_id=upload_id,
                        chunk_index=0,
                        data=data,
                    ),
                )

                handle_upload_complete(
                    FileUploadCompleteEvent(upload_id=upload_id),
                )

            # File should be saved as just 'passwd' in target_dir
            safe_file = Path(target_dir) / 'passwd'
            assert safe_file.exists()
            assert safe_file.read_bytes() == data

            # The traversal path should NOT have been created by the upload
            # (on Linux /etc/passwd pre-exists, so we verify the upload wrote
            # only to the safe location inside target_dir)
            assert safe_file.resolve().parent == Path(target_dir).resolve()
        finally:
            import shutil

            shutil.rmtree(target_dir, ignore_errors=True)
            _sessions.pop(upload_id, None)

    def test_missing_chunks_on_complete(self) -> None:
        """Complete with missing chunks dispatches error notification."""
        from unittest.mock import patch

        from upload_handler import (  # pyright: ignore[reportMissingImports]
            _sessions,
            handle_upload_chunk,
            handle_upload_complete,
            handle_upload_start,
        )

        target_dir = tempfile.mkdtemp()
        upload_id = 'test-missing'

        try:
            with patch('upload_handler.store') as mock_store:
                handle_upload_start(
                    FileUploadStartEvent(
                        upload_id=upload_id,
                        target_directory=target_dir,
                        filename='incomplete.bin',
                        total_size=3072,
                        total_chunks=3,
                        chunk_size=1024,
                    ),
                )

                # Only send 1 of 3 chunks
                handle_upload_chunk(
                    FileUploadChunkEvent(
                        upload_id=upload_id,
                        chunk_index=0,
                        data=b'\x00' * 1024,
                    ),
                )

                handle_upload_complete(
                    FileUploadCompleteEvent(upload_id=upload_id),
                )

                # Verify error notification was dispatched
                # Last dispatch call should be the error notification
                last_call = mock_store.dispatch.call_args
                assert last_call is not None
                action = last_call[0][0]
                assert action.notification.title == 'Upload Failed'
                assert 'Missing 2' in action.notification.content

            # File should NOT exist in target
            assert not (Path(target_dir) / 'incomplete.bin').exists()
        finally:
            import shutil

            shutil.rmtree(target_dir, ignore_errors=True)
            _sessions.pop(upload_id, None)

    def test_out_of_range_chunk_fails_upload(self) -> None:
        """A chunk index outside the announced range fails the session."""
        from unittest.mock import patch

        from upload_handler import (  # pyright: ignore[reportMissingImports]
            _sessions,
            handle_upload_chunk,
            handle_upload_start,
        )

        target_dir = tempfile.mkdtemp()
        upload_id = 'test-out-of-range'

        try:
            with patch('upload_handler.store') as mock_store:
                handle_upload_start(
                    FileUploadStartEvent(
                        upload_id=upload_id,
                        target_directory=target_dir,
                        filename='invalid.bin',
                        total_size=1024,
                        total_chunks=1,
                        chunk_size=1024,
                    ),
                )

                handle_upload_chunk(
                    FileUploadChunkEvent(
                        upload_id=upload_id,
                        chunk_index=1,
                        data=b'\x00' * 1024,
                    ),
                )

                assert upload_id not in _sessions
                action = mock_store.dispatch.call_args[0][0]
                assert action.notification.title == 'Upload Failed'
                assert 'chunk metadata' in action.notification.content
        finally:
            import shutil

            shutil.rmtree(target_dir, ignore_errors=True)
            _sessions.pop(upload_id, None)

    def test_invalid_start_metadata_fails_upload(self) -> None:
        """Start metadata must match the announced chunking scheme."""
        from unittest.mock import patch

        from upload_handler import (  # pyright: ignore[reportMissingImports]
            _sessions,
            handle_upload_start,
        )

        upload_id = 'test-invalid-metadata'
        with patch('upload_handler.store') as mock_store:
            handle_upload_start(
                FileUploadStartEvent(
                    upload_id=upload_id,
                    filename='invalid.bin',
                    total_size=1024,
                    total_chunks=2,
                    chunk_size=1024,
                ),
            )

            assert upload_id not in _sessions
            action = mock_store.dispatch.call_args[0][0]
            assert action.notification.title == 'Upload Failed'
            assert 'metadata' in action.notification.content

    async def test_await_completed_upload_raises_on_failure(self) -> None:
        """Waiters are rejected when an upload fails."""
        from ubo_app.utils.file_upload import (
            await_completed_upload,
            register_failed_upload,
        )

        upload_id = 'test-await-failure'
        register_failed_upload(upload_id, 'boom')

        with pytest.raises(RuntimeError, match='boom'):
            await await_completed_upload(upload_id)

    def test_invalid_target_directory(self) -> None:
        """Start with non-existent target directory dispatches error notification."""
        from unittest.mock import patch

        from upload_handler import (  # pyright: ignore[reportMissingImports]
            _sessions,
            handle_upload_start,
        )

        upload_id = 'test-bad-dir'
        with patch('upload_handler.store') as mock_store:
            handle_upload_start(
                FileUploadStartEvent(
                    upload_id=upload_id,
                    target_directory='/nonexistent/path/that/does/not/exist',
                    filename='test.bin',
                    total_size=1024,
                    total_chunks=1,
                    chunk_size=1024,
                ),
            )

            # Should dispatch an error notification
            mock_store.dispatch.assert_called()

        # No session should be created
        assert upload_id not in _sessions

    @pytest.fixture(autouse=True)
    def _cleanup_sessions(self) -> None:
        """Ensure no leftover sessions between tests."""
        from upload_handler import _sessions  # pyright: ignore[reportMissingImports]

        from ubo_app.utils import file_upload

        _sessions.clear()
        file_upload._completed_uploads.clear()  # noqa: SLF001
        file_upload._failed_uploads.clear()  # noqa: SLF001
        file_upload._upload_waiters.clear()  # noqa: SLF001
