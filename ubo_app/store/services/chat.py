# ruff: noqa: D100, D101
from __future__ import annotations

import time
from dataclasses import field
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

from immutable import Immutable
from redux import BaseAction, BaseEvent

if TYPE_CHECKING:
    from collections.abc import Sequence


class ChatRole(StrEnum):
    """Who authored a chat message."""

    USER = 'user'
    ASSISTANT = 'assistant'


class ChatMessageKind(StrEnum):
    """What kind of content a chat message carries."""

    TEXT = 'text'
    AUDIO = 'audio'


class ChatMessage(Immutable):
    """A single message in a chat session.

    This is the *UI-logic* representation of a message — the store owns the
    conversation history as a sequence of these. The renderer never sees a
    ``ChatMessage``; it only sees the resolved ``ChatBubbleData`` computed
    from it by ``get_chat_view_data``.
    """

    role: ChatRole
    id: str = field(default_factory=lambda: uuid4().hex)
    kind: ChatMessageKind = ChatMessageKind.TEXT
    text: str = ''
    # ``audio_id`` references an audio clip; ``audio_data`` carries the raw
    # bytes (populated in phase 2 when the assistant feeds real audio).
    audio_id: str = ''
    audio_data: bytes = b''
    # Normalized (0..1) bar heights for the waveform rendering. Deterministic
    # so window snapshots are stable.
    waveform: tuple[float, ...] = ()
    is_playing: bool = False
    timestamp: float = field(default_factory=time.time)


class ChatState(Immutable):
    """Redux slice holding the current chat session."""

    messages: Sequence[ChatMessage] = ()
    session_id: str = ''
    is_active: bool = False


class ChatAction(BaseAction): ...


class ChatStartSessionAction(ChatAction):
    """Start a fresh chat session and open the chat overlay."""

    session_id: str = field(default_factory=lambda: uuid4().hex)


class ChatEndSessionAction(ChatAction):
    """End the current chat session and close the chat overlay."""


class ChatAddMessageAction(ChatAction):
    """Append a message to the current chat session."""

    message: ChatMessage


class ChatAppendToMessageAction(ChatAction):
    """Append a chunk of streamed text to an existing message.

    Used to stream an assistant (or transcribed user) response into a
    speech bubble chunk-by-chunk as the text arrives.
    """

    message_id: str
    chunk: str


class ChatToggleAudioPlaybackAction(ChatAction):
    """Toggle play/stop on an audio message bubble."""

    message_id: str


class ChatClearAction(ChatAction):
    """Clear all messages from the current chat session."""


class ChatEvent(BaseEvent): ...


class ChatSessionStartedEvent(ChatEvent):
    """Emitted when a chat session starts."""

    session_id: str


class ChatSessionEndedEvent(ChatEvent):
    """Emitted when a chat session ends."""

    session_id: str


class ChatAudioPlaybackToggledEvent(ChatEvent):
    """Emitted when an audio bubble's playback state changes.

    Phase 2: the audio service consumes this to play/stop the real clip.
    """

    message_id: str
    is_playing: bool
