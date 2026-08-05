"""Filesystem-guard tests for ``microwakeword_engine``'s on-disk helpers.

``delete_model`` runs off-reducer on a ``model_id`` that can originate from a
remote gRPC action, so it must refuse anything but a real model pair living
directly in ``MODELS_DIR`` — in particular any path-traversal id.

The engine module is a namespace module under the service directory, so it's
loaded the same way ``test_openwakeword_model_files.py`` loads its counterpart.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-speech-recognition'


def _load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, Path]:
    """Load the engine module with ``MODELS_DIR`` pointed at a temp directory."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    module = importlib.reload(importlib.import_module('microwakeword_engine'))
    models_dir = tmp_path / 'models'
    models_dir.mkdir()
    monkeypatch.setattr(module, 'MODELS_DIR', models_dir)
    return module, models_dir


def _write_pair(models_dir: Path, model_id: str) -> None:
    (models_dir / f'{model_id}.json').write_text('{}')
    (models_dir / f'{model_id}.tflite').write_bytes(b'x')


def test_delete_model_removes_both_halves(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A model is a ``.json`` + ``.tflite`` pair; both go."""
    module, models_dir = _load(monkeypatch, tmp_path)
    _write_pair(models_dir, 'hey_luna')

    module.delete_model('hey_luna')

    assert not (models_dir / 'hey_luna.json').exists()
    assert not (models_dir / 'hey_luna.tflite').exists()


def test_delete_model_refuses_path_traversal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An id with ``..`` can't escape MODELS_DIR."""
    module, _models_dir = _load(monkeypatch, tmp_path)
    victim = tmp_path / 'victim.json'
    victim.write_text('{}')

    module.delete_model('../victim')

    assert victim.exists()


def test_delete_model_refuses_absolute_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An absolute id is rejected before any filesystem operation."""
    module, _models_dir = _load(monkeypatch, tmp_path)
    victim = tmp_path / 'absolute.json'
    victim.write_text('{}')

    module.delete_model(str(tmp_path / 'absolute'))

    assert victim.exists()


def test_delete_model_refuses_empty_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An empty id would resolve to MODELS_DIR itself."""
    module, models_dir = _load(monkeypatch, tmp_path)
    _write_pair(models_dir, 'keep_me')

    module.delete_model('')

    assert (models_dir / 'keep_me.json').exists()


def test_scan_models_requires_both_halves(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A half-downloaded model is not listed — every listed id must be loadable."""
    module, models_dir = _load(monkeypatch, tmp_path)
    (models_dir / 'orphan.json').write_text('{}')
    (models_dir / 'weights_only.tflite').write_bytes(b'x')
    _write_pair(models_dir, 'complete')

    assert module.scan_models() == ['complete']


def test_scan_models_ignores_partial_downloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """In-flight ``.part`` files must not surface as available models."""
    module, models_dir = _load(monkeypatch, tmp_path)
    (models_dir / 'hey_luna.json.part').write_text('{}')
    (models_dir / 'hey_luna.tflite.part').write_bytes(b'x')

    assert module.scan_models() == []


def test_scan_models_on_missing_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Before the first download the directory doesn't exist yet."""
    module, _models_dir = _load(monkeypatch, tmp_path)
    monkeypatch.setattr(module, 'MODELS_DIR', tmp_path / 'nonexistent')

    assert module.scan_models() == []
