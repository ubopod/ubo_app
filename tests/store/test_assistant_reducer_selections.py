"""Selection-setter, mute, and init branches of the assistant reducer.

The other ``test_assistant_*`` files each focus on one engine's download/voice
flow; this one pins the plain ``replace(state, selected_… = action.…)`` setters
and the init/passthrough guards that none of them exercise.

Class-identity discipline mirrors ``test_assistant_kokoro_voice.py``: integration
tests earlier in the suite wipe ``sys.modules``, so the reducer is exec'd from
file and every action/state class is read off ``reducer.__globals__`` — the one
generation the reducer's ``match`` binds against.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


@pytest.fixture(autouse=True)
def _isolated_persistent_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep AssistantState's persistent-store reads off the real file."""
    store_path = tmp_path / 'state.json'
    monkeypatch.setattr('ubo_app.constants.PERSISTENT_STORE_PATH', store_path)
    monkeypatch.setattr(
        'ubo_app.utils.persistent_store.PERSISTENT_STORE_PATH',
        store_path,
    )


def _load_reducer(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Any]:
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    from ubo_app.store.services import assistant as assistant_module

    importlib.reload(assistant_module)

    spec = importlib.util.spec_from_file_location(
        'assistant_service_reducer_selections',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.reducer


def _state(reducer: Callable[..., Any]) -> Any:  # noqa: ANN401
    result = reducer(None, reducer.__globals__['InitAction']())
    assert isinstance(result, reducer.__globals__['AssistantState'])
    return result


def test_none_state_without_init_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-init action against a None state is an initialization error."""
    reducer = _load_reducer(monkeypatch)
    with pytest.raises(reducer.__globals__['InitializationActionError']):
        reducer(None, reducer.__globals__['AssistantSetIsActiveAction'](is_active=True))


@pytest.mark.parametrize(
    ('action_name', 'kwargs', 'attribute', 'expected'),
    [
        ('AssistantSetIsActiveAction', {'is_active': True}, 'is_active', True),
        (
            'AssistantSetSelectedSTTAction',
            {'stt_name': 'whisper'},
            'selected_stt',
            'whisper',
        ),
        (
            'AssistantSetSelectedTTSAction',
            {'tts_name': 'piper'},
            'selected_tts',
            'piper',
        ),
        (
            'AssistantSetSelectedImageGeneratorAction',
            {'image_generator_name': 'firefly'},
            'selected_image_generator',
            'firefly',
        ),
        (
            'AssistantSetSelectedVoskModelAction',
            {'model_id': 'vosk-small'},
            'selected_vosk_model',
            'vosk-small',
        ),
    ],
)
def test_selection_setters(
    monkeypatch: pytest.MonkeyPatch,
    action_name: str,
    kwargs: dict[str, Any],
    attribute: str,
    expected: object,
) -> None:
    """Each selection setter writes its value straight onto the slice."""
    reducer = _load_reducer(monkeypatch)
    result = reducer(_state(reducer), reducer.__globals__[action_name](**kwargs))
    assert getattr(result, attribute) == expected


def test_input_mute_maps_to_microphone_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Muting the input device flips the assistant's microphone-mute flag."""
    reducer = _load_reducer(monkeypatch)
    audio_device = reducer.__globals__['AudioDevice']
    result = reducer(
        _state(reducer),
        reducer.__globals__['AudioSetMuteStatusAction'](
            device=audio_device.INPUT,
            is_mute=True,
        ),
    )
    assert result.is_microphone_mute is True


def test_unhandled_action_returns_state_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An action matching no case leaves the state untouched."""
    reducer = _load_reducer(monkeypatch)
    state = _state(reducer)
    assert reducer(state, reducer.__globals__['InitAction']()) is state


def test_ollama_and_vosk_downloads_emit_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Download requests turn into their download events."""
    reducer = _load_reducer(monkeypatch)
    state = _state(reducer)

    ollama = reducer(
        state,
        reducer.__globals__['AssistantDownloadOllamaModelAction'](model='llama3'),
    )
    assert any(
        isinstance(e, reducer.__globals__['AssistantDownloadOllamaModelEvent'])
        and e.model == 'llama3'
        for e in (ollama.events or [])
    )

    vosk = reducer(
        state,
        reducer.__globals__['AssistantDownloadVoskModelAction'](model_id='vosk-en'),
    )
    assert any(
        isinstance(e, reducer.__globals__['AssistantDownloadVoskModelEvent'])
        and e.model_id == 'vosk-en'
        for e in (vosk.events or [])
    )


def test_ollama_capabilities_and_downloaded_models_are_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capabilities merge per-model and downloaded lists replace wholesale."""
    reducer = _load_reducer(monkeypatch)
    state = _state(reducer)

    with_caps = reducer(
        state,
        reducer.__globals__['AssistantSetOllamaModelCapabilitiesAction'](
            model='llama3',
            capabilities=['tools', 'vision'],
        ),
    )
    assert with_caps.ollama_model_capabilities['llama3'] == ('tools', 'vision')

    with_models = reducer(
        state,
        reducer.__globals__['AssistantSetOllamaDownloadedModelsAction'](
            models=['a', 'b'],
        ),
    )
    assert with_models.ollama_downloaded_models == ('a', 'b')
    assert with_models.ollama_downloaded_models_refreshed is True


def test_ollama_thinking_toggle_is_recorded_per_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The thinking toggle is stored per model."""
    reducer = _load_reducer(monkeypatch)
    result = reducer(
        _state(reducer),
        reducer.__globals__['AssistantSetOllamaThinkingAction'](
            model='llama3',
            enabled=True,
        ),
    )
    state = result.state if hasattr(result, 'state') else result
    assert state.ollama_thinking_enabled['llama3'] is True


def test_vosk_downloaded_models_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vosk downloaded-model list is stored wholesale."""
    reducer = _load_reducer(monkeypatch)
    result = reducer(
        _state(reducer),
        reducer.__globals__['AssistantSetVoskDownloadedModelsAction'](
            models=['small', 'large'],
        ),
    )
    assert result.vosk_downloaded_models == ('small', 'large')
