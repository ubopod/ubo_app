"""Tests for the 090-chat service reducer.

Covers the chat session lifecycle — start/end (which push/pop the chat
overlay onto the navigation stack), appending text and audio messages, the
deterministic waveform fill for audio bubbles, and the audio play/stop
toggle.

NOTE: the reducer is loaded with the ``090-chat`` service directory on
``sys.path`` so ``from reducer import reducer`` resolves — same pattern as
``test_camera_reducer.py``. The store types are loaded inside the same
loader so the reducer's match-case and the test's constructed actions
reference the same class objects even after an integration test clears
``sys.modules``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from redux import CompleteReducerResult, InitAction

if TYPE_CHECKING:
    from collections.abc import Callable


def _import_store_types_and_reducer() -> tuple[Any, Callable[..., Any]]:
    """Load chat store types and the chat reducer together."""
    modules_before = set(sys.modules)

    from ubo_app.store.core import types as core_types
    from ubo_app.store.services import chat

    service_dir = str(
        Path(__file__).resolve().parents[2]
        / 'ubo_app'
        / 'services'
        / '090-chat',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    from reducer import reducer  # type: ignore[import-not-found]

    namespace: dict[str, Any] = {
        name: getattr(chat, name)
        for name in (
            'ChatAddMessageAction',
            'ChatAppendToMessageAction',
            'ChatAudioPlaybackToggledEvent',
            'ChatClearAction',
            'ChatEndSessionAction',
            'ChatMessage',
            'ChatMessageKind',
            'ChatRole',
            'ChatSessionEndedEvent',
            'ChatSessionStartedEvent',
            'ChatStartSessionAction',
            'ChatState',
            'ChatToggleAudioPlaybackAction',
        )
    }
    namespace['StackPushChatAction'] = core_types.StackPushChatAction
    namespace['StackPopChatAction'] = core_types.StackPopChatAction

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return namespace, reducer


_TYPES, reducer = _import_store_types_and_reducer()


def test_init_action_creates_empty_state() -> None:
    """InitAction must create an empty, inactive chat state."""
    state = reducer(None, InitAction())
    assert isinstance(state, _TYPES['ChatState'])
    assert state.messages == ()
    assert state.is_active is False


def test_start_session_opens_overlay() -> None:
    """ChatStartSessionAction resets history and pushes the chat overlay."""
    state = _TYPES['ChatState'](
        messages=(_TYPES['ChatMessage'](role=_TYPES['ChatRole'].USER),),
    )
    result = reducer(
        state,
        _TYPES['ChatStartSessionAction'](session_id='s1'),
    )
    assert isinstance(result, CompleteReducerResult)
    assert result.state.messages == ()
    assert result.state.is_active is True
    assert result.state.session_id == 's1'
    actions = list(result.actions or [])
    assert any(isinstance(a, _TYPES['StackPushChatAction']) for a in actions)
    events = list(result.events or [])
    assert any(isinstance(e, _TYPES['ChatSessionStartedEvent']) for e in events)


def test_end_session_closes_overlay() -> None:
    """ChatEndSessionAction deactivates the session and pops the overlay."""
    state = _TYPES['ChatState'](session_id='s1', is_active=True)
    result = reducer(state, _TYPES['ChatEndSessionAction']())
    assert isinstance(result, CompleteReducerResult)
    assert result.state.is_active is False
    assert any(
        isinstance(a, _TYPES['StackPopChatAction'])
        for a in (result.actions or [])
    )
    assert any(
        isinstance(e, _TYPES['ChatSessionEndedEvent'])
        for e in (result.events or [])
    )


def test_add_text_message_appends() -> None:
    """ChatAddMessageAction appends a text message to the conversation."""
    state = _TYPES['ChatState']()
    message = _TYPES['ChatMessage'](
        role=_TYPES['ChatRole'].ASSISTANT,
        kind=_TYPES['ChatMessageKind'].TEXT,
        text='hello',
    )
    new_state = reducer(state, _TYPES['ChatAddMessageAction'](message=message))
    assert len(new_state.messages) == 1
    assert new_state.messages[0].text == 'hello'


def test_add_audio_message_fills_deterministic_waveform() -> None:
    """An audio message with no waveform gets a deterministic one filled in."""
    state = _TYPES['ChatState']()
    message = _TYPES['ChatMessage'](
        role=_TYPES['ChatRole'].USER,
        kind=_TYPES['ChatMessageKind'].AUDIO,
        audio_id='clip-1',
    )
    first = reducer(state, _TYPES['ChatAddMessageAction'](message=message))
    second = reducer(state, _TYPES['ChatAddMessageAction'](message=message))
    waveform = first.messages[0].waveform
    assert len(waveform) > 0
    assert all(0.0 <= value <= 1.0 for value in waveform)
    # Deterministic: the same audio_id always yields the same waveform.
    assert first.messages[0].waveform == second.messages[0].waveform


def test_toggle_audio_playback_is_exclusive() -> None:
    """Toggling one audio bubble plays it and stops every other bubble."""
    playing = _TYPES['ChatMessage'](
        id='a',
        role=_TYPES['ChatRole'].USER,
        kind=_TYPES['ChatMessageKind'].AUDIO,
        audio_id='a',
        is_playing=True,
    )
    idle = _TYPES['ChatMessage'](
        id='b',
        role=_TYPES['ChatRole'].USER,
        kind=_TYPES['ChatMessageKind'].AUDIO,
        audio_id='b',
    )
    state = _TYPES['ChatState'](messages=(playing, idle))
    result = reducer(
        state,
        _TYPES['ChatToggleAudioPlaybackAction'](message_id='b'),
    )
    assert isinstance(result, CompleteReducerResult)
    by_id = {message.id: message for message in result.state.messages}
    assert by_id['b'].is_playing is True
    assert by_id['a'].is_playing is False
    events = list(result.events or [])
    assert any(
        isinstance(e, _TYPES['ChatAudioPlaybackToggledEvent'])
        and e.message_id == 'b'
        and e.is_playing is True
        for e in events
    )


def test_append_to_message_streams_text() -> None:
    """ChatAppendToMessageAction appends a chunk to the matching message."""
    message = _TYPES['ChatMessage'](
        id='a1',
        role=_TYPES['ChatRole'].ASSISTANT,
        kind=_TYPES['ChatMessageKind'].TEXT,
        text='Hel',
    )
    state = _TYPES['ChatState'](messages=(message,))

    state = reducer(
        state,
        _TYPES['ChatAppendToMessageAction'](message_id='a1', chunk='lo'),
    )
    assert state.messages[0].text == 'Hello'

    # An unknown message id is a no-op.
    unchanged = reducer(
        state,
        _TYPES['ChatAppendToMessageAction'](message_id='nope', chunk='!'),
    )
    assert unchanged.messages[0].text == 'Hello'


def test_clear_action_empties_messages() -> None:
    """ChatClearAction removes every message from the session."""
    state = _TYPES['ChatState'](
        messages=(_TYPES['ChatMessage'](role=_TYPES['ChatRole'].USER),),
    )
    new_state = reducer(state, _TYPES['ChatClearAction']())
    assert new_state.messages == ()
