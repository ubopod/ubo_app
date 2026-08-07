"""Lazy-load regression test for the core Vosk speech-recognition engine.

On first-time setup the Vosk model is downloaded *after* the engine has already
started (the command-interface wake slot is enabled by default, so the wake-word
engine runs at boot). The engine must not require the model at loop start — an eager
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

import pytest

from ubo_app.utils.async_evicting_queue import AsyncEvictingQueue

if TYPE_CHECKING:
    from types import ModuleType

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
        loaded_model_id=None,
        phrases=None,
        retry_at=0.0,
    )

    # Model not downloaded yet: engine stays unloaded, no crash, and
    # ``loaded_model_id`` does NOT advance so the model keeps being retried.
    state = await module.VoskEngine._reconcile(engine, state)  # noqa: SLF001
    assert state.recognizer is None
    assert state.loaded_model_id is None

    # Download lands on disk: the next reconcile builds the recognizer with no
    # app restart — the core of the fix. Reset ``retry_at`` to bypass the
    # back-off throttle (a wall-clock second would otherwise have to elapse).
    (tmp_path / 'm1').mkdir()
    state = state._replace(retry_at=0.0)
    state = await module.VoskEngine._reconcile(engine, state)  # noqa: SLF001
    assert state.recognizer is not None
    assert state.model is not None
    assert state.loaded_model_id == 'm1'


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
    state = module._RecognizerState(None, None, None, None, 0.0)  # noqa: SLF001

    for _ in range(3):
        # Reset the back-off each iteration so every pass actually re-attempts
        # the load (instead of being throttled out).
        state = state._replace(retry_at=0.0)
        state = await module.VoskEngine._reconcile(engine, state)  # noqa: SLF001
        assert state.recognizer is None
        assert state.loaded_model_id is None


async def test_reconcile_retries_switched_model_without_abandoning_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Switching to a not-ready model keeps retrying it, not silently stuck.

    Regression guard for the bug where ``loaded_model_id`` advanced to a
    not-yet-ready model, so the previous recognizer lingered and the new model
    was never loaded once it finished downloading.
    """
    module = _load_vosk_engine(monkeypatch)
    _install_fake_vosk(monkeypatch)
    monkeypatch.setattr(module, 'model_path_for', lambda model_id: tmp_path / model_id)

    engine = SimpleNamespace(grammar_lock=asyncio.Lock(), _phrases=None)

    # Start with model 'a' already loaded; the user then selects 'b' (absent).
    previous_recognizer = SimpleNamespace(kind='recognizer-a')
    state = module._RecognizerState(  # noqa: SLF001
        model=SimpleNamespace(kind='model-a'),
        recognizer=previous_recognizer,
        loaded_model_id='a',
        phrases=None,
        retry_at=0.0,
    )
    monkeypatch.setattr(module, '_read_selected_model', lambda: 'b')

    # 'b' isn't on disk yet: keep the working recognizer, do NOT advance
    # loaded_model_id (so 'b' keeps being retried).
    state = state._replace(retry_at=0.0)
    state = await module.VoskEngine._reconcile(engine, state)  # noqa: SLF001
    assert state.recognizer is previous_recognizer
    assert state.loaded_model_id == 'a'

    # 'b' finishes downloading: the retry loads it.
    (tmp_path / 'b').mkdir()
    state = state._replace(retry_at=0.0)
    state = await module.VoskEngine._reconcile(engine, state)  # noqa: SLF001
    assert state.recognizer is not previous_recognizer
    assert state.loaded_model_id == 'b'


class _FakeRecognizer:
    """Stands in for ``KaldiRecognizer``: raises like the real C binding does.

    ``vosk_recognizer_accept_waveform`` calls ``len(data)`` internally, so a
    non-bytes-like chunk raises ``TypeError: object of type 'int' has no
    len()`` — reproduced here without the real native dependency.
    """

    def __init__(self) -> None:
        self.seen: list[bytes] = []

    def AcceptWaveform(self, data: object) -> bool:  # noqa: N802
        if not isinstance(data, (bytes, bytearray)):
            msg = f"object of type '{type(data).__name__}' has no len()"
            raise TypeError(msg)
        self.seen.append(bytes(data))
        return False

    def PartialResult(self) -> str:  # noqa: N802
        return '{}'


async def test_run_survives_malformed_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-bytes-like chunk on the input queue must not kill ``_run``.

    Nothing else restarts the loop after it dies (``decide_running_state``
    only re-fires on a trigger-config change — see
    ``BackgroundRunningMixin``), so a single malformed chunk would otherwise
    silently and permanently stop speech recognition. Reproduces the crash
    from Sentry issue UBO-APP-RF (``TypeError: object of type 'int' has no
    len()`` from ``AcceptWaveform``).
    """
    module = _load_vosk_engine(monkeypatch)
    _install_fake_vosk(monkeypatch)

    fake_recognizer = _FakeRecognizer()
    state = module._RecognizerState(  # noqa: SLF001
        model=SimpleNamespace(kind='model'),
        recognizer=fake_recognizer,
        loaded_model_id='m1',
        phrases=None,
        retry_at=0.0,
    )

    async def _reconcile(_state: object) -> object:
        return state

    input_queue: AsyncEvictingQueue[object] = AsyncEvictingQueue(maxsize=5)
    await input_queue.put(5)
    await input_queue.put(b'ab')

    engine = SimpleNamespace(
        name='vosk',
        should_be_running=lambda: True,
        input_queue=input_queue,
        process_executor=None,
        ongoing_recognition=None,
        _reconcile=_reconcile,
    )

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(module.VoskEngine._run(engine), timeout=0.05)  # noqa: SLF001

    assert fake_recognizer.seen == [b'ab']
