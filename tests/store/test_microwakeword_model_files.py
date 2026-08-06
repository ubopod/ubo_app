"""Filesystem-guard tests for ``microwakeword_engine``'s on-disk helpers.

``delete_model`` runs off-reducer on a ``model_id`` that can originate from a
remote gRPC action, so it must refuse anything but a real model pair living
directly in ``MODELS_DIR`` — in particular any path-traversal id.

``validate_model`` and ``staging_paths`` are covered together because they're
two halves of one invariant: ``from_config`` resolves a model's weights from
the manifest's ``model`` key relative to the *manifest's own directory*, so the
download has to stage the pair under its final names for validation to find
them.

The engine module is a namespace module under the service directory, so it's
loaded the same way ``test_openwakeword_model_files.py`` loads its counterpart.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType

    import pytest

MANIFEST = {
    'type': 'micro',
    'wake_word': 'Hey Luna',
    'model': 'hey_luna.tflite',
    'micro': {'probability_cutoff': 0.63, 'sliding_window_size': 5},
}

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


def _stub_loader(module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Replace ``_load_model`` with a faithful stand-in; return its call log.

    Mirrors what ``MicroWakeWord.from_config`` does with the filesystem — read
    the manifest, then open ``config_path.parent / config['model']`` — without
    needing ``pymicro_wakeword`` or real TFLite weights.
    """
    calls: list[Path] = []

    def _load(config_path: Path) -> SimpleNamespace:
        calls.append(config_path)
        config = json.loads(config_path.read_text())
        (config_path.parent / config['model']).read_bytes()
        return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(module, '_load_model', _load)
    return calls


def test_validate_model_accepts_a_staged_pair(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A download staged by ``staging_paths`` validates before it's installed."""
    module, _models_dir = _load(monkeypatch, tmp_path)
    calls = _stub_loader(module, monkeypatch)
    staging = module.staging_paths('hey_luna')
    staging.directory.mkdir(parents=True)
    staging.config.write_text(json.dumps(MANIFEST))
    staging.weights.write_bytes(b'weights')

    assert module.validate_model(staging.config) is True
    assert calls == [staging.config]


def test_staging_paths_are_hidden_from_scan_models(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An in-flight download must not surface as an available model."""
    module, _models_dir = _load(monkeypatch, tmp_path)
    staging = module.staging_paths('hey_luna')
    staging.directory.mkdir(parents=True)
    staging.config.write_text(json.dumps(MANIFEST))
    staging.weights.write_bytes(b'weights')

    assert module.scan_models() == []


def test_validate_model_rejects_a_manifest_beside_missing_weights(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a manifest whose declared weights aren't beside it.

    The old ``.part``-suffixed layout: the weights are on disk, but not under
    the name the manifest declares. This must fail *before* reaching the
    loader, whose null-interpreter deref segfaults rather than raising.
    """
    module, models_dir = _load(monkeypatch, tmp_path)
    calls = _stub_loader(module, monkeypatch)
    config = models_dir / 'hey_luna.json.part'
    config.write_text(json.dumps(MANIFEST))
    (models_dir / 'hey_luna.tflite.part').write_bytes(b'weights')

    assert module.validate_model(config) is False
    assert calls == []


def test_validate_model_rejects_a_corrupt_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A truncated ``.json`` half can't be parsed for its weights reference."""
    module, models_dir = _load(monkeypatch, tmp_path)
    calls = _stub_loader(module, monkeypatch)
    config = models_dir / 'hey_luna.json'
    config.write_text('{"type": "micro"')

    assert module.validate_model(config) is False
    assert calls == []


def test_scan_models_on_missing_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Before the first download the directory doesn't exist yet."""
    module, _models_dir = _load(monkeypatch, tmp_path)
    monkeypatch.setattr(module, 'MODELS_DIR', tmp_path / 'nonexistent')

    assert module.scan_models() == []
