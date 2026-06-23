"""Tests for deleting downloaded assistant models.

Two layers are covered:

* Reducer wiring — each ``AssistantDelete*Action`` emits the matching
  ``AssistantDelete*Event`` the service subscribes to (mirrors the existing
  download-action tests). The reducer is loaded in isolation with the same
  ``importlib`` discipline as ``test_assistant_piper_voice.py`` so it survives
  the ``sys.modules`` wipe integration tests perform.
* Engine file logic — ``PiperEngine.delete_voice`` unlinks the voice files and
  ``VoskEngine.delete_model`` removes the extracted directory. Both are driven
  against a stand-in ``self`` with a fake store (the ``test_generic_llm_engine``
  pattern) so no real store or event loop wiring is needed.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import pytest
    from redux import BaseAction

    from ubo_app.engines.piper import PiperEngine
    from ubo_app.engines.vosk import VoskEngine
    from ubo_app.store.services.assistant import AssistantState


SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


def _load_assistant(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Load the assistant reducer plus the delete action/event symbols."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    from ubo_app.store.services import assistant as assistant_module

    assistant_module = importlib.reload(assistant_module)

    spec = importlib.util.spec_from_file_location(
        'assistant_service_reducer_delete',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return SimpleNamespace(
        reducer=module.reducer,
        AssistantDeleteOllamaModelAction=(
            assistant_module.AssistantDeleteOllamaModelAction
        ),
        AssistantDeleteOllamaModelEvent=(
            assistant_module.AssistantDeleteOllamaModelEvent
        ),
        AssistantDeletePiperVoiceAction=(
            assistant_module.AssistantDeletePiperVoiceAction
        ),
        AssistantDeletePiperVoiceEvent=(
            assistant_module.AssistantDeletePiperVoiceEvent
        ),
        AssistantDeleteKokoroAction=assistant_module.AssistantDeleteKokoroAction,
        AssistantDeleteKokoroEvent=assistant_module.AssistantDeleteKokoroEvent,
        AssistantDeleteVoskModelAction=(
            assistant_module.AssistantDeleteVoskModelAction
        ),
        AssistantDeleteVoskModelEvent=(
            assistant_module.AssistantDeleteVoskModelEvent
        ),
    )


def _init_action(ns: SimpleNamespace) -> BaseAction:
    init_action_type = cast(
        'type[BaseAction]',
        ns.reducer.__globals__['InitAction'],
    )
    return init_action_type()


def _initial_state(ns: SimpleNamespace) -> AssistantState:
    return cast('AssistantState', ns.reducer(None, _init_action(ns)))


def test_delete_ollama_model_emits_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting an Ollama model emits a delete event for the engine handler."""
    from redux import CompleteReducerResult

    ns = _load_assistant(monkeypatch)
    result = ns.reducer(
        _initial_state(ns),
        ns.AssistantDeleteOllamaModelAction(model='qwen3:1.7b'),
    )
    assert isinstance(result, CompleteReducerResult)
    assert result.events is not None
    assert any(
        isinstance(e, ns.AssistantDeleteOllamaModelEvent)
        and e.model == 'qwen3:1.7b'
        for e in result.events
    )


def test_delete_piper_voice_emits_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting a Piper voice emits a delete event carrying the voice id."""
    from redux import CompleteReducerResult

    ns = _load_assistant(monkeypatch)
    voice_id = 'de/de_DE/thorsten/medium/de_DE-thorsten-medium'
    result = ns.reducer(
        _initial_state(ns),
        ns.AssistantDeletePiperVoiceAction(voice_id=voice_id),
    )
    assert isinstance(result, CompleteReducerResult)
    assert result.events is not None
    assert any(
        isinstance(e, ns.AssistantDeletePiperVoiceEvent)
        and e.voice_id == voice_id
        for e in result.events
    )


def test_delete_kokoro_emits_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deleting the Kokoro bundle emits a (payload-less) delete event."""
    from redux import CompleteReducerResult

    ns = _load_assistant(monkeypatch)
    result = ns.reducer(
        _initial_state(ns),
        ns.AssistantDeleteKokoroAction(),
    )
    assert isinstance(result, CompleteReducerResult)
    assert result.events is not None
    assert any(
        isinstance(e, ns.AssistantDeleteKokoroEvent) for e in result.events
    )


def test_delete_vosk_model_emits_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting a Vosk model emits a delete event carrying the model id."""
    from redux import CompleteReducerResult

    ns = _load_assistant(monkeypatch)
    model_id = 'vosk-model-small-de-0.15'
    result = ns.reducer(
        _initial_state(ns),
        ns.AssistantDeleteVoskModelAction(model_id=model_id),
    )
    assert isinstance(result, CompleteReducerResult)
    assert result.events is not None
    assert any(
        isinstance(e, ns.AssistantDeleteVoskModelEvent)
        and e.model_id == model_id
        for e in result.events
    )


async def test_piper_delete_voice_removes_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``delete_voice`` unlinks both the ``.onnx`` and ``.onnx.json`` files."""
    from ubo_app.engines import piper as piper_module

    voice_id = 'en/en_US/kristin/medium/en_US-kristin-medium'
    onnx = tmp_path / 'voice.onnx'
    metadata = tmp_path / 'voice.onnx.json'
    onnx.write_text('model')
    metadata.write_text('{}')

    monkeypatch.setattr(piper_module, 'model_path_for', lambda _vid: onnx)
    monkeypatch.setattr(piper_module, 'json_path_for', lambda _vid: metadata)
    monkeypatch.setattr(
        piper_module,
        'store',
        SimpleNamespace(dispatch=lambda *_a, **_k: None),
    )

    refreshed: list[bool] = []

    async def _refresh() -> None:
        refreshed.append(True)

    engine = cast('PiperEngine', SimpleNamespace(refresh_downloaded_voices=_refresh))

    await piper_module.PiperEngine.delete_voice(engine, voice_id)

    assert not onnx.exists()
    assert not metadata.exists()
    assert refreshed == [True]


async def test_vosk_delete_model_removes_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``delete_model`` removes the extracted model directory tree."""
    from ubo_app.engines import vosk as vosk_module

    model_id = 'vosk-model-small-en-us-0.15'
    model_dir = tmp_path / model_id
    model_dir.mkdir()
    (model_dir / 'README').write_text('weights')

    monkeypatch.setattr(
        vosk_module,
        'model_path_for',
        lambda mid: tmp_path / mid,
    )
    monkeypatch.setattr(
        vosk_module,
        'store',
        SimpleNamespace(dispatch=lambda *_a, **_k: None),
    )

    refreshed: list[bool] = []

    async def _refresh() -> None:
        refreshed.append(True)

    engine = cast(
        'VoskEngine',
        SimpleNamespace(refresh_downloaded_models=_refresh),
    )

    await vosk_module.VoskEngine.delete_model(engine, model_id)

    assert not model_dir.exists()
    assert refreshed == [True]
