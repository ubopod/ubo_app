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
            'ChatSendUserMessageAction',
            'ChatSessionEndedEvent',
            'ChatSessionStartedEvent',
            'ChatSetMessageTextAction',
            'ChatStartSessionAction',
            'ChatState',
            'ChatToggleAudioPlaybackAction',
            'ChatUserMessageSentEvent',
        )
    }
    namespace['StackPushChatAction'] = core_types.StackPushChatAction
    namespace['StackPopChatAction'] = core_types.StackPopChatAction

    # Cross-service action types the chat reducer now observes to stamp
    # ``last_activity_time`` (mirrors the display-blank-timer pattern).
    from ubo_app.store.services import audio as audio_module

    namespace['AudioPlayAudioSequenceAction'] = (
        audio_module.AudioPlayAudioSequenceAction
    )
    namespace['AudioPlaybackDoneAction'] = audio_module.AudioPlaybackDoneAction
    namespace['AudioSample'] = audio_module.AudioSample

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


def test_set_message_text_replaces_wholesale() -> None:
    """ChatSetMessageTextAction overwrites a message's text (STT cumulative)."""
    message = _TYPES['ChatMessage'](
        id='u1',
        role=_TYPES['ChatRole'].USER,
        kind=_TYPES['ChatMessageKind'].TEXT,
        text='hel',
    )
    state = _TYPES['ChatState'](messages=(message,))

    # Cumulative STT frame revises the partial hypothesis — replace, don't
    # append.
    state = reducer(
        state,
        _TYPES['ChatSetMessageTextAction'](message_id='u1', text='hello'),
    )
    assert state.messages[0].text == 'hello'

    # A second revision overwrites the first.
    state = reducer(
        state,
        _TYPES['ChatSetMessageTextAction'](
            message_id='u1',
            text='hello there',
        ),
    )
    assert state.messages[0].text == 'hello there'

    # An unknown message id is a no-op.
    unchanged = reducer(
        state,
        _TYPES['ChatSetMessageTextAction'](message_id='nope', text='x'),
    )
    assert unchanged.messages[0].text == 'hello there'


def test_send_user_message_appends_and_emits_event() -> None:
    """ChatSendUserMessageAction adds a user bubble and notifies responders."""
    state = _TYPES['ChatState']()

    result = reducer(
        state,
        _TYPES['ChatSendUserMessageAction'](text='hello there'),
    )
    assert isinstance(result, CompleteReducerResult)
    assert len(result.state.messages) == 1
    message = result.state.messages[0]
    assert message.role == _TYPES['ChatRole'].USER
    assert message.kind == _TYPES['ChatMessageKind'].TEXT
    assert message.text == 'hello there'

    events = list(result.events or [])
    assert any(
        isinstance(event, _TYPES['ChatUserMessageSentEvent'])
        and event.text == 'hello there'
        and event.message_id == message.id
        for event in events
    )


def test_clear_action_empties_messages() -> None:
    """ChatClearAction removes every message from the session."""
    state = _TYPES['ChatState'](
        messages=(_TYPES['ChatMessage'](role=_TYPES['ChatRole'].USER),),
    )
    new_state = reducer(state, _TYPES['ChatClearAction']())
    assert new_state.messages == ()


def _state_for_activity() -> Any:  # noqa: ANN401
    """Active session with a known stale ``last_activity_time``."""
    return _TYPES['ChatState'](
        session_id='s1',
        is_active=True,
        last_activity_time=0.0,  # ancient; should be bumped by activity
    )


def test_start_session_stamps_last_activity_time() -> None:
    """``ChatStartSessionAction`` initialises ``last_activity_time``."""
    result = reducer(None, InitAction())
    result = reducer(result, _TYPES['ChatStartSessionAction'](session_id='s1'))
    state = result.state if isinstance(result, CompleteReducerResult) else result
    assert state.last_activity_time is not None
    assert state.last_activity_time > 0.0


def test_end_session_clears_last_activity_time() -> None:
    """``ChatEndSessionAction`` clears ``last_activity_time``."""
    state = _state_for_activity()
    state = state.__class__(
        messages=state.messages,
        session_id=state.session_id,
        is_active=True,
        last_activity_time=12345.6,
    )
    result = reducer(state, _TYPES['ChatEndSessionAction']())
    new_state = result.state if isinstance(result, CompleteReducerResult) else result
    assert new_state.last_activity_time is None


def test_add_message_bumps_last_activity_time() -> None:
    """``ChatAddMessageAction`` bumps ``last_activity_time`` past its old value."""
    state = _state_for_activity()
    message = _TYPES['ChatMessage'](
        role=_TYPES['ChatRole'].USER,
        kind=_TYPES['ChatMessageKind'].TEXT,
        text='hi',
    )
    new_state = reducer(state, _TYPES['ChatAddMessageAction'](message=message))
    assert new_state.last_activity_time is not None
    assert new_state.last_activity_time > 0.0


def test_append_to_message_bumps_last_activity_time() -> None:
    """Streaming-chunk action bumps ``last_activity_time``."""
    state = _state_for_activity()
    state = state.__class__(
        messages=(
            _TYPES['ChatMessage'](
                id='m1',
                role=_TYPES['ChatRole'].ASSISTANT,
                kind=_TYPES['ChatMessageKind'].TEXT,
                text='hi',
            ),
        ),
        session_id=state.session_id,
        is_active=True,
        last_activity_time=0.0,
    )
    new_state = reducer(
        state,
        _TYPES['ChatAppendToMessageAction'](message_id='m1', chunk='!'),
    )
    assert new_state.last_activity_time is not None
    assert new_state.last_activity_time > 0.0


def test_pipecat_audio_sequence_flips_is_audio_playing() -> None:
    """First pipecat chunk queued sets ``is_audio_playing`` True without bumping time.

    Chunks are queued faster than they play out, so timing the dismiss
    off the queue timestamp would close the chat mid-utterance. The flag
    keeps the dismiss loop suppressed; ``last_activity_time`` gets
    anchored later by ``AudioPlaybackDoneAction``.
    """
    state = _state_for_activity()
    sample = _TYPES['AudioSample'](
        data=b'\x00' * 32,
        channels=1,
        rate=16000,
        width=2,
    )
    new_state = reducer(
        state,
        _TYPES['AudioPlayAudioSequenceAction'](
            sample=sample,
            id='assistant:pipecat:turn-1',
            index=0,
        ),
    )
    assert new_state.is_audio_playing is True
    # Crucially, ``last_activity_time`` did NOT move forward on the play
    # action — only playback-done can advance the dismiss countdown.
    assert new_state.last_activity_time == 0.0


def test_subsequent_pipecat_chunks_keep_is_audio_playing(
) -> None:
    """Follow-up chunks while already playing are no-ops on state shape."""
    state = _TYPES['ChatState'](
        session_id='s1',
        is_active=True,
        last_activity_time=0.0,
        is_audio_playing=True,
    )
    sample = _TYPES['AudioSample'](
        data=b'\x00' * 32,
        channels=1,
        rate=16000,
        width=2,
    )
    new_state = reducer(
        state,
        _TYPES['AudioPlayAudioSequenceAction'](
            sample=sample,
            id='assistant:pipecat:turn-1',
            index=5,
        ),
    )
    assert new_state.is_audio_playing is True
    assert new_state.last_activity_time == 0.0


def test_non_pipecat_audio_sequence_does_not_set_is_audio_playing() -> None:
    """Audio chunks from chimes / file-system playback don't keep chat open."""
    state = _state_for_activity()
    sample = _TYPES['AudioSample'](
        data=b'\x00' * 32,
        channels=1,
        rate=16000,
        width=2,
    )
    new_state = reducer(
        state,
        _TYPES['AudioPlayAudioSequenceAction'](
            sample=sample,
            id='assistant:assistant_request:foo',  # not pipecat
            index=0,
        ),
    )
    assert new_state.is_audio_playing is False
    assert new_state.last_activity_time == 0.0


def test_pipecat_audio_playback_done_clears_flag_and_bumps_activity() -> None:
    """``AudioPlaybackDoneAction`` for pipecat is the authoritative "quiet" signal.

    The audio service dispatches it once its play loop exits because the
    buffer fully drained — only at *this* moment should the 7 s idle
    countdown start.
    """
    state = _TYPES['ChatState'](
        session_id='s1',
        is_active=True,
        last_activity_time=0.0,
        is_audio_playing=True,
    )
    new_state = reducer(
        state,
        _TYPES['AudioPlaybackDoneAction'](id='assistant:pipecat:turn-1'),
    )
    assert new_state.is_audio_playing is False
    assert new_state.last_activity_time is not None
    assert new_state.last_activity_time > 0.0


def test_non_pipecat_audio_playback_done_is_noop() -> None:
    """Playback-done for unrelated audio leaves the chat state alone."""
    state = _TYPES['ChatState'](
        session_id='s1',
        is_active=True,
        last_activity_time=0.0,
        is_audio_playing=True,
    )
    new_state = reducer(
        state,
        _TYPES['AudioPlaybackDoneAction'](id='chime:wifi-connected'),
    )
    assert new_state.is_audio_playing is True
    assert new_state.last_activity_time == 0.0


def test_audio_actions_inactive_session_is_noop() -> None:
    """Audio activity does not revive a closed chat session."""
    state = _TYPES['ChatState'](session_id='s1', is_active=False)
    new_state = reducer(
        state,
        _TYPES['AudioPlaybackDoneAction'](id='assistant:pipecat:turn-1'),
    )
    assert new_state.is_audio_playing is False
    assert new_state.last_activity_time is None


def test_end_session_clears_audio_playing_flag() -> None:
    """``ChatEndSessionAction`` resets ``is_audio_playing`` for cleanliness."""
    state = _TYPES['ChatState'](
        session_id='s1',
        is_active=True,
        last_activity_time=12345.6,
        is_audio_playing=True,
    )
    result = reducer(state, _TYPES['ChatEndSessionAction']())
    new_state = result.state if isinstance(result, CompleteReducerResult) else result
    assert new_state.is_audio_playing is False
