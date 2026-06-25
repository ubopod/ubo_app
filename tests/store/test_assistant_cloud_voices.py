"""Tests for the cloud TTS voice-selection actions on the assistant reducer.

Covers ``AssistantSetSelectedVoiceAction`` (emits ``AssistantVoiceChangedEvent``)
and the ElevenLabs voice-list actions (add / delete / set-available cache).

Uses the same ``importlib`` discipline as ``test_assistant_piper_voice.py``: the
reducer + classes are pulled from a freshly reloaded namespace so the suite
survives the ``sys.modules`` wipe integration tests perform.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import pytest
    from redux import BaseAction

    from ubo_app.store.services.assistant import AssistantState

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


def _load(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Load the assistant reducer plus the cloud-voice symbols namespace."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    from ubo_app.store.services import assistant as assistant_module

    assistant_module = importlib.reload(assistant_module)

    spec = importlib.util.spec_from_file_location(
        'assistant_service_reducer_cloud_voices',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return SimpleNamespace(reducer=module.reducer, assistant=assistant_module)


def _initial_state(ns: SimpleNamespace) -> AssistantState:
    init_action = cast('type[BaseAction]', ns.reducer.__globals__['InitAction'])()
    return cast('AssistantState', ns.reducer(None, init_action))


def test_set_selected_voice_updates_state_and_emits_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting a cloud voice updates ``selected_voices`` and emits the event."""
    from redux import CompleteReducerResult

    ns = _load(monkeypatch)
    a = ns.assistant
    state = _initial_state(ns)

    result = ns.reducer(
        state,
        a.AssistantSetSelectedVoiceAction(
            tts_name=a.AssistantTTSName.OPENAI,
            voice_id='nova',
        ),
    )

    assert isinstance(result, CompleteReducerResult)
    assert result.state.selected_voices[a.AssistantTTSName.OPENAI] == 'nova'
    assert result.events is not None
    assert any(
        isinstance(event, a.AssistantVoiceChangedEvent)
        and event.tts_name == a.AssistantTTSName.OPENAI
        and event.voice_id == 'nova'
        for event in result.events
    )


def test_set_selected_voice_deepgram_aura(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting a Deepgram Aura voice updates state and emits the event."""
    from redux import CompleteReducerResult

    ns = _load(monkeypatch)
    a = ns.assistant
    state = _initial_state(ns)

    result = ns.reducer(
        state,
        a.AssistantSetSelectedVoiceAction(
            tts_name=a.AssistantTTSName.DEEPGRAM,
            voice_id='aura-2-thalia-en',
        ),
    )

    assert isinstance(result, CompleteReducerResult)
    assert (
        result.state.selected_voices[a.AssistantTTSName.DEEPGRAM]
        == 'aura-2-thalia-en'
    )
    assert result.events is not None
    assert any(
        isinstance(event, a.AssistantVoiceChangedEvent)
        and event.tts_name == a.AssistantTTSName.DEEPGRAM
        and event.voice_id == 'aura-2-thalia-en'
        for event in result.events
    )


def test_add_elevenlabs_voice_with_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adding a voice stores an entry; re-adding updates the name in place."""
    ns = _load(monkeypatch)
    a = ns.assistant
    state = _initial_state(ns)

    state = cast(
        'AssistantState',
        ns.reducer(
            state,
            a.AssistantAddElevenLabsVoiceAction(
                voice_id='abc123',
                name='Deep Voice Man',
            ),
        ),
    )
    assert state.elevenlabs_voices == (
        a.ElevenLabsVoiceEntry(id='abc123', label='Deep Voice Man'),
    )

    # Re-adding the same id updates its name without duplicating.
    state = cast(
        'AssistantState',
        ns.reducer(
            state,
            a.AssistantAddElevenLabsVoiceAction(voice_id='abc123', name='Narrator'),
        ),
    )
    assert state.elevenlabs_voices == (
        a.ElevenLabsVoiceEntry(id='abc123', label='Narrator'),
    )


def test_add_multiple_elevenlabs_voices_accumulate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Distinct voice ids accumulate so the user can pick among them."""
    ns = _load(monkeypatch)
    a = ns.assistant
    state = _initial_state(ns)

    for voice_id in ('abc123', 'def456'):
        state = cast(
            'AssistantState',
            ns.reducer(
                state,
                a.AssistantAddElevenLabsVoiceAction(voice_id=voice_id),
            ),
        )

    assert [voice.id for voice in state.elevenlabs_voices] == ['abc123', 'def456']


def test_delete_elevenlabs_voice_falls_back_to_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting the selected EL voice resets to '' and notifies the subprocess."""
    from redux import CompleteReducerResult

    ns = _load(monkeypatch)
    a = ns.assistant
    state = replace(
        _initial_state(ns),
        elevenlabs_voices=(
            a.ElevenLabsVoiceEntry(id='abc123', label='Deep Voice Man'),
            a.ElevenLabsVoiceEntry(id='def456', label=''),
        ),
        selected_voices={a.AssistantTTSName.ELEVENLABS: 'abc123'},
    )

    result = ns.reducer(
        state,
        a.AssistantDeleteElevenLabsVoiceAction(voice_id='abc123'),
    )

    assert isinstance(result, CompleteReducerResult)
    assert [voice.id for voice in result.state.elevenlabs_voices] == ['def456']
    assert result.state.selected_voices[a.AssistantTTSName.ELEVENLABS] == ''
    # The subprocess only learns of cloud voice changes via this event, so a
    # deleted-while-selected voice must emit one (with the '' fallback).
    assert result.events is not None
    assert any(
        isinstance(event, a.AssistantVoiceChangedEvent)
        and event.tts_name == a.AssistantTTSName.ELEVENLABS
        and event.voice_id == ''
        for event in result.events
    )


def test_delete_unselected_elevenlabs_voice_keeps_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting a non-selected voice leaves the current selection intact."""
    ns = _load(monkeypatch)
    a = ns.assistant
    state = replace(
        _initial_state(ns),
        elevenlabs_voices=(
            a.ElevenLabsVoiceEntry(id='abc123', label=''),
            a.ElevenLabsVoiceEntry(id='def456', label=''),
        ),
        selected_voices={a.AssistantTTSName.ELEVENLABS: 'def456'},
    )

    new_state = cast(
        'AssistantState',
        ns.reducer(
            state,
            a.AssistantDeleteElevenLabsVoiceAction(voice_id='abc123'),
        ),
    )

    assert [voice.id for voice in new_state.elevenlabs_voices] == ['def456']
    assert new_state.selected_voices[a.AssistantTTSName.ELEVENLABS] == 'def456'


def test_set_elevenlabs_available_voices_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fetched-voice cache is replaced wholesale on the set action."""
    ns = _load(monkeypatch)
    a = ns.assistant
    state = _initial_state(ns)
    voices = (
        a.ElevenLabsVoiceEntry(id='v1', label='Rachel'),
        a.ElevenLabsVoiceEntry(id='v2', label='Adam'),
    )

    new_state = cast(
        'AssistantState',
        ns.reducer(
            state,
            a.AssistantSetElevenLabsAvailableVoicesAction(voices=voices),
        ),
    )

    assert new_state.elevenlabs_available_voices == voices
