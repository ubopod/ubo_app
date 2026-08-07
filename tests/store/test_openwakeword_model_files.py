"""Filesystem-guard tests for ``openwakeword_engine.delete_model``.

``delete_model`` runs off-reducer on a ``model_id`` that can originate from a
remote gRPC action, so it must refuse anything but a real wake-word model file
living directly in ``MODELS_DIR`` — in particular the shared helper models the
pipeline depends on, and any path-traversal id.

The engine module is a namespace module under the service directory, so it's
loaded the same way ``test_speech_recognition_wake_words.py`` loads the reducer.
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import Any

import pytest

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-speech-recognition'


def _load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, Path]:
    """Load the engine module with ``MODELS_DIR`` pointed at a temp directory."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    module = importlib.reload(importlib.import_module('openwakeword_engine'))
    models_dir = tmp_path / 'models'
    models_dir.mkdir()
    monkeypatch.setattr(module, 'MODELS_DIR', models_dir)
    return module, models_dir


def test_delete_model_removes_real_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A real model stem is unlinked."""
    module, models_dir = _load(monkeypatch, tmp_path)
    (models_dir / 'my_word.onnx').write_bytes(b'x')

    module.delete_model('my_word')

    assert not (models_dir / 'my_word.onnx').exists()


def test_delete_model_refuses_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Shared helper models are never deleted (they'd break every wake word)."""
    module, models_dir = _load(monkeypatch, tmp_path)
    (models_dir / 'embedding_model.onnx').write_bytes(b'x')

    module.delete_model('embedding_model')

    assert (models_dir / 'embedding_model.onnx').exists()


def test_delete_model_refuses_path_traversal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An id with path separators / ``..`` can't escape MODELS_DIR."""
    module, _models_dir = _load(monkeypatch, tmp_path)
    victim = tmp_path / 'victim.onnx'
    victim.write_bytes(b'x')

    module.delete_model('../victim')

    assert victim.exists()


async def test_run_survives_malformed_chunk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A non-bytes-like chunk on the input queue must not kill ``_run``.

    Nothing else restarts the loop after it dies (``decide_running_state``
    only re-fires on a trigger-config change — see
    ``BackgroundRunningMixin``), so a single malformed chunk would otherwise
    silently and permanently stop wake-word detection. Reproduces the crash
    from Sentry issue UBO-APP-RE (``TypeError: can't extend bytearray with
    int``).
    """
    module, _models_dir = _load(monkeypatch, tmp_path)
    mixin_module = importlib.import_module('abstraction.wake_word_recognition_mixin')
    WakeTrigger = mixin_module.WakeTrigger  # noqa: N806

    engine = module.OpenWakeWordEngine()
    engine.triggers = (WakeTrigger(id='trigger-id', value='hey_test'),)
    engine._model = object()  # noqa: SLF001

    await engine.input_queue.put(5)
    await engine.input_queue.put(b'ab')

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(engine._run(), timeout=0.05)  # noqa: SLF001

    assert engine._audio_buffer == bytearray(b'ab')  # noqa: SLF001


def test_helpers_available_requires_both_feature_models(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``helpers_available`` is True only once both feature extractors are present.

    The custom-upload flow gates on this so a model can't be added (and shown as
    usable) before the helpers a ``Model`` load requires exist on disk.
    """
    module, models_dir = _load(monkeypatch, tmp_path)
    assert module.helpers_available() is False

    (models_dir / 'melspectrogram.onnx').write_bytes(b'x')
    assert module.helpers_available() is False

    (models_dir / 'embedding_model.onnx').write_bytes(b'x')
    assert module.helpers_available() is True
