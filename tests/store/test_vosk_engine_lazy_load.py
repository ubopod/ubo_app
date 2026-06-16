"""Lazy-load regression test for the core Vosk speech-recognition engine.

On first-time setup the Vosk model is downloaded *after* the engine has already
started (``is_intents_active`` defaults to ``True``, so the wake-word engine
runs at boot). The engine must not require the model at loop start — an eager
``Model(...)`` load crashes the background task and nothing reliably restarts it
once the download finishes, leaving recognition dead until an app restart.
Instead ``_run`` reconciles before each chunk and builds the recognizer the
moment the model lands on disk.

Loads ``vosk_engine.py`` via ``importlib`` (like ``test_mic_buffer.py``) and
drives ``VoskEngine._reconcile`` against a minimal stand-in ``self`` — it only
touches ``self.grammar_lock`` and ``self._phrases`` — so the test needs neither
real Vosk nor a fully constructed engine.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    import pytest

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-speech-recognition'


def _load_vosk_engine(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load ``vosk_engine.py`` in isolation, returning the module object."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    spec = importlib.util.spec_from_file_location(
        'vosk_engine_test_module',
        SERVICE_PATH / 'vosk_engine.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _install_fake_vosk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real ``vosk`` module so model loads return cheap sentinels."""
    fake = types.ModuleType('vosk')
    fake.Model = lambda **_kwargs: SimpleNamespace(kind='model')  # pyright: ignore[reportAttributeAccessIssue]
    fake.KaldiRecognizer = lambda *_args: SimpleNamespace(kind='recognizer')  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setitem(sys.modules, 'vosk', fake)


async def test_reconcile_waits_then_self_heals_when_model_appears(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """No recognizer while the model is missing; built once it's downloaded."""
    module = _load_vosk_engine(monkeypatch)
    _install_fake_vosk(monkeypatch)
    monkeypatch.setattr(module, '_read_selected_model', lambda: 'm1')
    monkeypatch.setattr(module, 'model_path_for', lambda model_id: tmp_path / model_id)

    engine = SimpleNamespace(
        grammar_lock=asyncio.Lock(),
        _phrases=('okay ubo', '[unk]'),
    )
    state = module._RecognizerState(  # noqa: SLF001
        model=None,
        recognizer=None,
        model_id=None,
        phrases=None,
    )

    # Model not downloaded yet: engine stays unloaded, no crash.
    state = await module.VoskEngine._reconcile(engine, state)  # noqa: SLF001
    assert state.recognizer is None
    assert state.model_id == 'm1'

    # Download lands on disk: the next reconcile builds the recognizer with no
    # app restart — the core of the fix.
    (tmp_path / 'm1').mkdir()
    state = await module.VoskEngine._reconcile(engine, state)  # noqa: SLF001
    assert state.recognizer is not None
    assert state.model is not None
    assert state.model_id == 'm1'


async def test_reconcile_keeps_waiting_while_model_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Repeated reconciles with an absent model never build a recognizer."""
    module = _load_vosk_engine(monkeypatch)
    _install_fake_vosk(monkeypatch)
    monkeypatch.setattr(module, '_read_selected_model', lambda: 'absent')
    monkeypatch.setattr(module, 'model_path_for', lambda model_id: tmp_path / model_id)

    engine = SimpleNamespace(grammar_lock=asyncio.Lock(), _phrases=None)
    state = module._RecognizerState(None, None, None, None)  # noqa: SLF001

    for _ in range(3):
        state = await module.VoskEngine._reconcile(engine, state)  # noqa: SLF001
        assert state.recognizer is None
