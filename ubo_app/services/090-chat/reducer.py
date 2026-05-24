# ruff: noqa: D100, D103
from __future__ import annotations

import datetime
import hashlib
from dataclasses import replace

from redux import (
    CompleteReducerResult,
    FinishAction,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.core.types import StackPopChatAction, StackPushChatAction
from ubo_app.store.services.audio import (
    AudioPlayAudioSequenceAction,
    AudioPlaybackDoneAction,
)
from ubo_app.store.services.chat import (
    ChatAction,
    ChatAddMessageAction,
    ChatAppendToMessageAction,
    ChatAudioPlaybackToggledEvent,
    ChatClearAction,
    ChatEndSessionAction,
    ChatEvent,
    ChatMessage,
    ChatMessageKind,
    ChatRole,
    ChatSendUserMessageAction,
    ChatSessionEndedEvent,
    ChatSessionStartedEvent,
    ChatSetMessageTextAction,
    ChatStartSessionAction,
    ChatState,
    ChatToggleAudioPlaybackAction,
    ChatUserMessageSentEvent,
)

# Action types we observe to bump ``last_activity_time`` even though the
# chat reducer doesn't own them — pipecat's TTS chunks land on the bus
# faster than they play, and the matching ``AudioPlaybackDoneAction``
# is the only authoritative "speaker has actually gone quiet" signal.
Action = (
    InitAction
    | ChatAction
    | AudioPlayAudioSequenceAction
    | AudioPlaybackDoneAction
)
ResultAction = StackPushChatAction | StackPopChatAction

_WAVEFORM_BAR_COUNT = 28

# The assistant service's ``_communicate`` handler namespaces pipecat TTS
# audio sequences as ``assistant:pipecat:{frame.id}`` — match this prefix
# to filter out unrelated audio (chimes, file-system playback, etc.).
_PIPECAT_AUDIO_ID_PREFIX = 'assistant:pipecat:'


def _now() -> float:
    return datetime.datetime.now(tz=datetime.UTC).timestamp()


def _waveform_for(audio_id: str) -> tuple[float, ...]:
    """Derive a deterministic waveform from an id.

    Bar heights are normalized to 0.15..1.0. Deterministic so window
    snapshots of audio bubbles stay stable across runs.
    """
    digest = hashlib.sha256(audio_id.encode('utf-8')).digest()
    return tuple(
        0.15 + (digest[i % len(digest)] / 255) * 0.85
        for i in range(_WAVEFORM_BAR_COUNT)
    )


def reducer(
    state: ChatState | None,
    action: Action,
) -> ReducerResult[ChatState, ResultAction, ChatEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return ChatState()
        raise InitializationActionError(action)

    match action:
        case ChatStartSessionAction():
            # A fresh session clears any previous conversation and opens the
            # chat overlay by pushing a ChatStackItem onto the nav stack.
            return CompleteReducerResult(
                state=ChatState(
                    messages=(),
                    session_id=action.session_id,
                    is_active=True,
                    last_activity_time=_now(),
                    is_audio_playing=False,
                ),
                actions=[StackPushChatAction(session_id=action.session_id)],
                events=[ChatSessionStartedEvent(session_id=action.session_id)],
            )

        case ChatEndSessionAction():
            return CompleteReducerResult(
                state=replace(
                    state,
                    is_active=False,
                    last_activity_time=None,
                    is_audio_playing=False,
                ),
                actions=[StackPopChatAction()],
                events=[ChatSessionEndedEvent(session_id=state.session_id)],
            )

        case ChatAddMessageAction():
            message = action.message
            # Fill in a deterministic waveform for audio bubbles so the
            # renderer always has bars to draw (real audio arrives in
            # phase 2).
            if message.kind == ChatMessageKind.AUDIO and not message.waveform:
                message = replace(
                    message,
                    waveform=_waveform_for(message.audio_id or message.id),
                )
            return replace(
                state,
                messages=(*state.messages, message),
                last_activity_time=_now(),
            )

        case ChatSendUserMessageAction():
            # Turn a sent message into a USER bubble and notify responders.
            message = ChatMessage(
                role=ChatRole.USER,
                kind=ChatMessageKind.TEXT,
                text=action.text,
            )
            return CompleteReducerResult(
                state=replace(
                    state,
                    messages=(*state.messages, message),
                    last_activity_time=_now(),
                ),
                events=[
                    ChatUserMessageSentEvent(
                        text=action.text,
                        message_id=message.id,
                    ),
                ],
            )

        case ChatAppendToMessageAction():
            # Stream a text chunk into an existing bubble.
            new_messages = tuple(
                replace(message, text=message.text + action.chunk)
                if message.id == action.message_id
                else message
                for message in state.messages
            )
            return replace(
                state,
                messages=new_messages,
                last_activity_time=_now(),
            )

        case ChatSetMessageTextAction():
            # Replace an existing bubble's text wholesale (cumulative STT).
            new_messages = tuple(
                replace(message, text=action.text)
                if message.id == action.message_id
                else message
                for message in state.messages
            )
            return replace(
                state,
                messages=new_messages,
                last_activity_time=_now(),
            )

        case ChatToggleAudioPlaybackAction():
            target = next(
                (m for m in state.messages if m.id == action.message_id),
                None,
            )
            if target is None:
                return state
            new_is_playing = not target.is_playing
            # Only one clip plays at a time — stop every other bubble.
            new_messages = tuple(
                replace(
                    message,
                    is_playing=(
                        new_is_playing
                        if message.id == action.message_id
                        else False
                    ),
                )
                for message in state.messages
            )
            return CompleteReducerResult(
                state=replace(state, messages=new_messages),
                events=[
                    ChatAudioPlaybackToggledEvent(
                        message_id=action.message_id,
                        is_playing=new_is_playing,
                    ),
                ],
            )

        case ChatClearAction():
            return replace(state, messages=())

        # Cross-service activity signals from the audio service. Only the
        # live pipecat pipeline drives the chat overlay; one-shot
        # programmatic requests (transcribe/synthesize/complete) share the
        # bus but should not keep the chat open.
        case AudioPlayAudioSequenceAction() if (
            state.is_active and action.id.startswith(_PIPECAT_AUDIO_ID_PREFIX)
        ):
            # First chunk queued — speaker is about to talk. Don't bump
            # ``last_activity_time``: chunks are queued faster than they
            # play, so the timestamp would race ahead of real playback.
            # The dismiss task gates on ``is_audio_playing``.
            if state.is_audio_playing:
                return state
            return replace(state, is_audio_playing=True)

        case AudioPlaybackDoneAction() if (
            state.is_active and action.id.startswith(_PIPECAT_AUDIO_ID_PREFIX)
        ):
            # Speaker has actually gone quiet (audio service's play loop
            # exited — buffer fully drained). Now anchor the 7 s idle
            # countdown to *this* moment.
            return replace(
                state,
                is_audio_playing=False,
                last_activity_time=_now(),
            )

        case FinishAction():
            return ChatState()

        case _:
            return state
