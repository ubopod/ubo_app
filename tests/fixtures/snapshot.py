"""Window snapshot fixture using gRPC screenshot round-trip."""

from __future__ import annotations

import threading
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from str_to_bool import str_to_bool

if TYPE_CHECKING:
    from collections.abc import Generator

    from _pytest.fixtures import SubRequest  # pyright: ignore[reportPrivateImportUsage]


def write_png(image_path: Path, data: bytes) -> None:
    """Write raw PNG bytes to a file."""
    with image_path.open('wb') as f:
        f.write(data)


class WindowSnapshot:
    """Context object for tests taking snapshots of the window via store events."""

    def __init__(
        self: WindowSnapshot,
        *,
        test_id: str,
        path: Path,
        override: bool,
        make_screenshots: bool,
        prefix: str | None,
    ) -> None:
        """Create a new window snapshot context."""
        self.prefix = prefix
        self._is_failed = False
        self._is_closed = False
        self.override = override
        self.make_screenshots = make_screenshots
        self.test_counter: dict[str | None, int] = defaultdict(int)
        self._latest_hash: str | None = None
        self._latest_data: bytes | None = None

        file = path.with_suffix('').name
        self.results_dir = Path(
            path.parent / 'results' / file / test_id.split('::')[-1][5:],
        )
        if self.results_dir.exists():
            prefix_element = ''
            if self.prefix:
                prefix_element = self.prefix + '-'
            for file_path in self.results_dir.glob(
                f'window-{prefix_element}*'
                if override
                else f'window-{prefix_element}*.mismatch.*',
            ):
                file_path.unlink()
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def _capture_screenshot(self: WindowSnapshot) -> None:
        """Dispatch TakeScreenshotAction and wait for ScreenshotDataEvent.

        If no GUI client is running, the screenshot round-trip cannot complete.
        In that case, we set a stable dummy hash so stability checks pass.
        Uses a short timeout to avoid blocking when GUI is not available,
        but does not permanently cache the result since the GUI may connect
        after an initial delay (e.g., splash screen).
        """
        from ubo_app.store.core.types import ScreenshotDataEvent, TakeScreenshotAction
        from ubo_app.store.main import store

        event = threading.Event()

        def _on_screenshot_data(screenshot_event: ScreenshotDataEvent) -> None:
            self._latest_hash = screenshot_event.hash
            self._latest_data = screenshot_event.data
            event.set()

        unsubscribe = store.subscribe_event(
            ScreenshotDataEvent,
            _on_screenshot_data,
        )

        store.dispatch(TakeScreenshotAction())

        # Use a shorter timeout after the first successful capture
        timeout = 3 if self._latest_data is not None else 15
        event.wait(timeout=timeout)
        unsubscribe()

        if not event.is_set():
            msg = (
                f'Screenshot capture timed out after {timeout}s'
                ' - GUI is not responding. Check that the GUI'
                ' subprocess is running and connected via gRPC.'
            )
            raise TimeoutError(msg)

    @property
    def hash(self: WindowSnapshot) -> str:
        """Return the hash of the current window content."""
        self._capture_screenshot()
        if self._latest_hash is None:
            msg = 'No screenshot data available'
            raise RuntimeError(msg)
        return self._latest_hash

    def get_filename(self: WindowSnapshot, title: str | None) -> str:
        """Get the filename for the snapshot."""
        title_element = ''
        if title:
            title_element = title + '-'
        prefix_element = ''
        if self.prefix:
            prefix_element = self.prefix + '-'
        return (
            f"""window-{prefix_element}{title_element}{self.test_counter[title]:03d}"""
        )

    def take(self: WindowSnapshot, title: str | None = None) -> None:
        """Take a snapshot of the content of the window."""
        if self._is_closed:
            msg = (
                'Snapshot context is closed, make sure `window_snapshot` is before any '
                'fixture dispatching actions in the fixtures list'
            )
            raise RuntimeError(msg)

        self._capture_screenshot()

        filename = self.get_filename(title)
        path = Path(self.results_dir / filename)
        hash_path = path.with_suffix('.hash')
        image_path = path.with_suffix('.png')
        hash_mismatch_path = path.with_suffix('.mismatch.hash')
        image_mismatch_path = path.with_suffix('.mismatch.png')

        new_snapshot = self._latest_hash
        if new_snapshot is None:
            msg = 'No screenshot data available'
            raise RuntimeError(msg)

        if self.override:
            hash_path.write_text(f'// {filename}\n{new_snapshot}\n')
            if self.make_screenshots and self._latest_data is not None:
                write_png(image_path, self._latest_data)
        else:
            if hash_path.exists():
                old_snapshot = hash_path.read_text().split('\n', 1)[1][:-1]
            else:
                old_snapshot = None
            if old_snapshot != new_snapshot:
                self._is_failed = True
                hash_mismatch_path.write_text(  # pragma: no cover
                    f'// MISMATCH: {filename}\n{new_snapshot}\n',
                )
                if self.make_screenshots and self._latest_data is not None:
                    write_png(image_mismatch_path, self._latest_data)
            elif self.make_screenshots and self._latest_data is not None:
                write_png(image_path, self._latest_data)
            assert new_snapshot == old_snapshot, (
                f'Window snapshot mismatch - {filename}'
            )

        self.test_counter[title] += 1

    def close(self: WindowSnapshot) -> None:
        """Close the snapshot context."""
        self._is_closed = True
        if self._is_failed:
            return
        for title in self.test_counter:
            filename = self.get_filename(title)
            hash_path = (self.results_dir / filename).with_suffix('.hash')

            assert not hash_path.exists(), f'Snapshot {filename} not taken'


@pytest.fixture
def snapshot_prefix() -> str:
    """Return the prefix for the snapshots."""
    from ubo_app.utils import IS_RPI

    if IS_RPI:
        return 'rpi'

    return 'desktop'


@pytest.fixture
def window_snapshot(
    request: SubRequest,
    snapshot_prefix: str | None,
) -> Generator[WindowSnapshot, None, None]:
    """Take a screenshot of the window via store event round-trip."""
    import os

    override = (
        request.config.getoption(
            '--override-window-snapshots',
            default=cast(
                'Any',
                str_to_bool(os.environ.get('UBO_TEST_OVERRIDE_SNAPSHOTS', 'false')),
            ),
        )
        is True
    )
    make_screenshots = (
        request.config.getoption(
            '--make-screenshots',
            default=cast(
                'Any',
                str_to_bool(os.environ.get('UBO_TEST_MAKE_SCREENSHOTS', 'false')),
            ),
        )
        is True
    )

    context = WindowSnapshot(
        test_id=request.node.nodeid,
        path=request.node.path,
        override=override,
        make_screenshots=make_screenshots,
        prefix=snapshot_prefix,
    )
    yield context
    context.close()
