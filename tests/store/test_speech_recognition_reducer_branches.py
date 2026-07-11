"""Init, phrase, wake-word-model, and report branches of the SR reducer.

The command/wake-word tests focus on their own flows; this file pins the
remaining reducer branches. The reducer is exec'd from the service directory
(relative imports) and every class is read off ``reducer.__globals__`` — the
one generation its ``match`` binds against, resilient to earlier ``app_context``
tests evicting modules from ``sys.modules``.
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

SERVICE_PATH = (
    Path(__file__).resolve().parents[2]
    / 'ubo_app'
    / 'services'
    / '090-speech-recognition'
)


@pytest.fixture
def reducer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Callable[..., Any]:
    """Load the speech-recognition reducer from the service directory."""
    store_path = tmp_path / 'state.json'
    monkeypatch.setattr(
        'ubo_app.utils.persistent_store.PERSISTENT_STORE_PATH',
        store_path,
    )
    monkeypatch.setattr(
        'ubo_app.constants.PERSISTENT_STORE_PATH',
        store_path,
        raising=False,
    )
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    importlib.reload(importlib.import_module('commands'))

    spec = importlib.util.spec_from_file_location(
        'speech_recognition_reducer_branches',
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
    assert isinstance(result, reducer.__globals__['SpeechRecognitionState'])
    return result


def test_none_state_without_init_raises(reducer: Callable[..., Any]) -> None:
    """A non-init action against a None state is an initialization error."""
    with pytest.raises(reducer.__globals__['InitializationActionError']):
        reducer(
            None,
            reducer.__globals__['SpeechRecognitionSetAssistantEnabledAction'](
                enabled=True,
            ),
        )


def test_set_conversation_end_phrases(reducer: Callable[..., Any]) -> None:
    """Conversation-end phrases are stored verbatim on the slice."""
    action = reducer.__globals__['SpeechRecognitionSetConversationEndPhrasesAction']
    result = reducer(_state(reducer), action(phrases=('goodbye', 'stop')))
    assert result.conversation_end_phrases == ('goodbye', 'stop')


def test_wake_word_models_status_recorded(reducer: Callable[..., Any]) -> None:
    """A model-status report is recorded for its engine."""
    action = reducer.__globals__['WakeWordSetModelsStatusAction']
    engine = reducer.__globals__['WakeWordEngineName']
    status = reducer.__globals__['WakeWordModelStatus']
    result = reducer(
        _state(reducer),
        action(engine_name=engine.OPENWAKEWORD, status=status.AVAILABLE),
    )
    assert any(
        entry.engine == engine.OPENWAKEWORD and entry.status == status.AVAILABLE
        for entry in result.wake_word_models_status
    )


def test_available_models_ignored_for_non_openwakeword(
    reducer: Callable[..., Any],
) -> None:
    """Available-model lists only apply to OpenWakeWord; others are no-ops."""
    action = reducer.__globals__['WakeWordSetAvailableModelsAction']
    engine = reducer.__globals__['WakeWordEngineName']
    state = _state(reducer)
    assert reducer(state, action(engine=engine.VOSK, models=('a',))) is state


def test_available_models_stored_for_openwakeword(
    reducer: Callable[..., Any],
) -> None:
    """OpenWakeWord available models are stored on the slice."""
    action = reducer.__globals__['WakeWordSetAvailableModelsAction']
    engine = reducer.__globals__['WakeWordEngineName']
    result = reducer(
        _state(reducer),
        action(engine=engine.OPENWAKEWORD, models=('hey_ubo',)),
    )
    assert result.openwakeword_models == ('hey_ubo',)


def test_report_speech_returns_to_idle(reducer: Callable[..., Any]) -> None:
    """A speech report drops the recognizer back to IDLE."""
    from ubo_app.store.services.speech_recognition import SpeechRecognitionEngineName

    action = reducer.__globals__['SpeechRecognitionReportSpeechAction']
    result = reducer(
        _state(reducer),
        action(engine_name=SpeechRecognitionEngineName.VOSK, text='hello', audio=b''),
    )
    idle = reducer.__globals__['SpeechRecognitionStatus'].IDLE
    assert result.state.status == idle


def test_trigger_intents_while_busy_settles_to_idle(
    reducer: Callable[..., Any],
) -> None:
    """An intents trigger while already busy falls through to IDLE."""
    from dataclasses import replace

    action = reducer.__globals__['SpeechRecognitionTriggerModeAction']
    wake_mode = reducer.__globals__['WakeMode']
    status = reducer.__globals__['SpeechRecognitionStatus']
    # Non-IDLE status skips the "start intents" arm so it reaches the final
    # fall-through that resets to IDLE.
    state = replace(_state(reducer), status=status.INTENTS_WAITING)

    result = reducer(state, action(mode=wake_mode.INTENTS))

    assert result.state.status == status.IDLE


def test_wake_word_detection_with_invalid_engine_is_safe(
    reducer: Callable[..., Any],
) -> None:
    """An unrecognized engine name resolves to no trigger without crashing."""
    action = reducer.__globals__['SpeechRecognitionReportWakeWordDetectionAction']
    state = _state(reducer)
    # A bogus engine name raises inside WakeWordEngineName(...) and is caught;
    # with no resolvable trigger the slice is returned unchanged in value.
    result = reducer(state, action(engine_name='bogus', trigger_id='t1'))
    resolved = result.state if hasattr(result, 'state') else result
    assert resolved == state


def test_unhandled_action_returns_state_unchanged(
    reducer: Callable[..., Any],
) -> None:
    """An action matching no case leaves the state untouched."""
    state = _state(reducer)
    assert reducer(state, reducer.__globals__['InitAction']()) is state
