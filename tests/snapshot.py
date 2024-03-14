"""Let the test check snapshots of the window during execution."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from logging import Logger
    from pathlib import Path

    from _pytest.fixtures import SubRequest
    from numpy._typing import NDArray


make_screenshots = os.environ.get('UBO_TEST_MAKE_SCREENSHOTS', '0') == '1'
override_snapshots = os.environ.get('UBO_TEST_OVERRIDE_SNAPSHOTS', '0') == '1'


def write_image(image_path: Path, array: NDArray) -> None:
    """Write the `NDAarray` as an image to the given path."""
    import png

    png.Writer(
        width=array.shape[0],
        height=array.shape[1],
        greyscale=False,  # pyright: ignore [reportArgumentType]
        bitdepth=8,
    ).write(
        image_path.open('wb'),
        array.reshape(-1, array.shape[0] * 3).tolist(),
    )


class SnapshotContext:
    """Context object for tests taking snapshots of the window."""

    def __init__(self: SnapshotContext, id: str, path: Path, logger: Logger) -> None:
        """Create a new snapshot context."""
        self.test_counter = 0
        self.id = id
        self.results_dir = path.parent / 'results'
        self.logger = logger
        if make_screenshots:
            self.logger.info(
                f'Snapshot will be saved in "{self.results_dir}" for test id {id}',  # noqa: G004
            )
            self.results_dir.mkdir(exist_ok=True)

    @property
    def hash(self: SnapshotContext) -> str:
        """Return the hash of the current window."""
        import hashlib

        from headless_kivy_pi.config import _display

        array = _display.raw_data
        data = array.tobytes()
        sha256 = hashlib.sha256()
        sha256.update(data)
        return sha256.hexdigest()

    def take(self: SnapshotContext) -> None:
        """Take a snapshot of the current window."""
        filename = f'{"_".join(self.id.split(":")[-1:])}-{self.test_counter:03d}'

        from headless_kivy_pi.config import _display

        path = self.results_dir / filename
        hash_path = path.with_suffix('.hash')

        hash_ = self.hash
        array = _display.raw_data
        data = array.tobytes()
        if hash_path.exists() and not override_snapshots:
            old_hash = hash_path.read_text()
            if old_hash != hash_:
                write_image(path.with_suffix('.mismatch.png'), array)
            assert old_hash == hash_, f'Hash mismatch: {old_hash} != {hash_}'
        hash_path.write_text(hash_)

        if data is not None and make_screenshots:
            write_image(path.with_suffix('.png'), array)
        self.test_counter += 1


@pytest.fixture()
def snapshot(request: SubRequest, logger: Logger) -> SnapshotContext:
    """Take a snapshot of the current window."""
    return SnapshotContext(request.node.nodeid, request.node.path, logger)
