"""Unit tests for the service-directory load filter.

Guards against orphaned ``~``-prefixed service directories (left by an
interrupted in-place ``pip install --force-reinstall``) shadowing the canonical
``0NN-*`` dirs at load time. See ``is_loadable_service_dir`` in
``ubo_app/service_thread.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.service_thread import is_loadable_service_dir

if TYPE_CHECKING:
    from pathlib import Path


def test_canonical_service_dirs_are_loadable(tmp_path: Path) -> None:
    """Directories following the ``NNN-name`` convention load."""
    for name in ('000-audio', '090-web-ui', '090-infrared'):
        path = tmp_path / name
        path.mkdir()
        assert is_loadable_service_dir(path) is True


def test_tilde_backup_dir_is_skipped(tmp_path: Path) -> None:
    """A ``~``-prefixed pip backup twin is not loadable."""
    path = tmp_path / '~90-web-ui'
    path.mkdir()
    assert is_loadable_service_dir(path) is False


def test_hidden_dir_is_skipped(tmp_path: Path) -> None:
    """A dot-prefixed (hidden) directory is not loadable."""
    path = tmp_path / '.cache'
    path.mkdir()
    assert is_loadable_service_dir(path) is False


def test_non_directory_is_skipped(tmp_path: Path) -> None:
    """A regular file is not a loadable service directory."""
    path = tmp_path / '090-web-ui'
    path.write_text('not a dir')
    assert is_loadable_service_dir(path) is False
