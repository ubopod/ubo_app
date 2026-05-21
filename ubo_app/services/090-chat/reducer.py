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
from ubo_app.store.services.chat import (
    ChatAction,
    ChatAddMessageAction,
    ChatAppendToMessageAction,
    ChatAudioPlaybackToggledEvent,
    ChatClearAction,
    ChatEndSessionAction,
    ChatEvent,
    ChatMessageKind,
    ChatSessionEndedEvent,
    ChatSessionStartedEvent,
    ChatStartSessionAction,
    ChatState,
    ChatToggleAudioPlaybackAction,
)

Action = InitAction | ChatAction
ResultAction = StackPushChatAction | StackPopChatAction

_WAVEFORM_BAR_COUNT = 28


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
                ),
                actions=[StackPushChatAction(session_id=action.session_id)],
                events=[ChatSessionStartedEvent(session_id=action.session_id)],
            )

        case ChatEndSessionAction():
            return CompleteReducerResult(
                state=replace(state, is_active=False),
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
            return replace(state, messages=(*state.messages, message))

        case ChatAppendToMessageAction():
            # Stream a text chunk into an existing bubble.
            new_messages = tuple(
                replace(message, text=message.text + action.chunk)
                if message.id == action.message_id
                else message
                for message in state.messages
            )
            return replace(state, messages=new_messages)

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

        case FinishAction():
            return ChatState()

        case _:
            return state
