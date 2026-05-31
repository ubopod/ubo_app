# ruff: noqa: D100, D103
from __future__ import annotations

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
    AudioSequenceSource,
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

# Cap on retained chat messages. Long-running sessions over gRPC pay an
# ``O(history)`` cost on every view-snapshot, so trim from the head once
# the cap is exceeded. 200 messages covers a typical session and stays
# well below the per-message recompute knee.
_CHAT_HISTORY_MAX_MESSAGES = 200


def _trim_messages(
    messages: tuple[ChatMessage, ...],
) -> tuple[ChatMessage, ...]:
    if len(messages) <= _CHAT_HISTORY_MAX_MESSAGES:
        return messages
    return messages[-_CHAT_HISTORY_MAX_MESSAGES:]


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
            # The revision bumps from whatever previous-session value so
            # the view selector always sees a change even on session reset.
            return CompleteReducerResult(
                state=ChatState(
                    messages=(),
                    session_id=action.session_id,
                    is_active=True,
                    last_activity_time=action.timestamp,
                    is_audio_playing=False,
                    messages_revision=state.messages_revision + 1,
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
                messages=_trim_messages((*state.messages, message)),
                last_activity_time=action.timestamp,
                messages_revision=state.messages_revision + 1,
            )

        case ChatSendUserMessageAction():
            # Turn a sent message into a USER bubble and notify responders.
            message = ChatMessage(
                role=ChatRole.USER,
                kind=ChatMessageKind.TEXT,
                text=action.text,
            )
            if action.message_id:
                message = replace(message, id=action.message_id)
            return CompleteReducerResult(
                state=replace(
                    state,
                    messages=_trim_messages((*state.messages, message)),
                    last_activity_time=action.timestamp,
                    messages_revision=state.messages_revision + 1,
                ),
                events=[
                    ChatUserMessageSentEvent(
                        text=action.text,
                        message_id=message.id,
                    ),
                ],
            )

        case ChatAppendToMessageAction():
            # Stream a text chunk into an existing bubble. The append-only
            # streaming path is the LLM token hot path — locate the target
            # by index once and splice it back in, avoiding the per-token
            # ``O(history)`` tuple rebuild the comprehension produced.
            target_index = next(
                (
                    i
                    for i, message in enumerate(state.messages)
                    if message.id == action.message_id
                ),
                None,
            )
            if target_index is None:
                return replace(state, last_activity_time=action.timestamp)
            target = state.messages[target_index]
            replaced = replace(target, text=target.text + action.chunk)
            new_messages = (
                *state.messages[:target_index],
                replaced,
                *state.messages[target_index + 1 :],
            )
            return replace(
                state,
                messages=new_messages,
                last_activity_time=action.timestamp,
                messages_revision=state.messages_revision + 1,
            )

        case ChatSetMessageTextAction():
            # Replace an existing bubble's text wholesale (cumulative STT).
            target_index = next(
                (
                    i
                    for i, message in enumerate(state.messages)
                    if message.id == action.message_id
                ),
                None,
            )
            if target_index is None:
                return replace(state, last_activity_time=action.timestamp)
            target = state.messages[target_index]
            replaced = replace(target, text=action.text)
            new_messages = (
                *state.messages[:target_index],
                replaced,
                *state.messages[target_index + 1 :],
            )
            return replace(
                state,
                messages=new_messages,
                last_activity_time=action.timestamp,
                messages_revision=state.messages_revision + 1,
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
            return replace(
                state,
                messages=(),
                messages_revision=state.messages_revision + 1,
            )

        # Cross-service activity signals from the audio service. Only the
        # live pipecat pipeline drives the chat overlay; one-shot
        # programmatic requests (transcribe/synthesize/complete) share the
        # bus but tag their sequences with ``AudioSequenceSource.OTHER`` so
        # they don't keep the chat open.
        case AudioPlayAudioSequenceAction() if (
            state.is_active
            and action.source is AudioSequenceSource.ASSISTANT_LIVE
        ):
            # First chunk queued — speaker is about to talk. Don't bump
            # ``last_activity_time``: chunks are queued faster than they
            # play, so the timestamp would race ahead of real playback.
            # The dismiss task gates on ``is_audio_playing``.
            if state.is_audio_playing:
                return state
            return replace(state, is_audio_playing=True)

        case AudioPlaybackDoneAction() if (
            state.is_active
            and action.source is AudioSequenceSource.ASSISTANT_LIVE
        ):
            # Speaker has actually gone quiet (audio service's play loop
            # exited — buffer fully drained). Now anchor the 7 s idle
            # countdown to *this* moment (the audio service stamps the
            # action's ``timestamp`` when it dispatches).
            return replace(
                state,
                is_audio_playing=False,
                last_activity_time=action.timestamp,
            )

        case FinishAction():
            return ChatState()

        case _:
            return state
