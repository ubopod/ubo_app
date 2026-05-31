# ruff: noqa: D100, D101
from __future__ import annotations

import time
from dataclasses import field
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.clock import default_now

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
    # ``audio_id`` references an audio clip by id; the actual bytes live
    # in the audio service's per-id cache, NOT in Redux state.
    audio_id: str = ''
    # TODO(phase-2): do NOT populate ``audio_data`` from any reducer or  # noqa: FIX002
    # producer. Real audio bytes belong in an ``audio_id``→``bytes`` cache
    # owned by ``ubo_app/services/000-audio/audio_manager.py`` (the
    # renderer fetches lazily by ``audio_id``). Putting bytes here makes
    # them part of every Redux snapshot and gRPC ``ChatState`` push —
    # quickly bloats snapshots/network for any non-trivial audio. This
    # field stays as a typed placeholder; a unit test enforces ``b''``.
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
    # Timestamp of the most recent activity that should keep the chat
    # overlay open: chat actions and pipecat audio playback-done. The
    # chat service's idle-dismiss task compares this against ``now``
    # and dispatches ``ChatEndSessionAction`` after the timeout. Same
    # pattern as ``DisplayState.last_activity_time``.
    last_activity_time: float | None = None
    # True between the first pipecat ``AudioPlayAudioSequenceAction``
    # landing on the bus and the matching ``AudioPlaybackDoneAction``
    # — i.e. while the speaker is *actually* talking. The dismiss task
    # refuses to fire while this is True, because ``AudioPlayAudioSequenceAction``
    # chunks are queued faster than they play (often the entire reply
    # is queued in ~1 s for a 30 s utterance), so timing dismiss off
    # the *queue* timestamp would close the chat mid-utterance. Pipecat
    # doesn't interleave TTS streams, so a plain bool is enough; the
    # audio service's play loop fires the matching done event once its
    # buffer fully drains.
    is_audio_playing: bool = False
    # Monotonic counter bumped by every reducer case that mutates
    # ``messages`` (add/append/set/clear). The view-autorun selector
    # observes this single int instead of hashing every message field
    # per token — drops per-token selector equality work from
    # ``O(history)`` to ``O(1)``. Never compared across sessions.
    messages_revision: int = 0


class ChatAction(BaseAction): ...


class ChatStartSessionAction(ChatAction):
    """Start a fresh chat session and open the chat overlay."""

    session_id: str = field(default_factory=lambda: uuid4().hex)
    # ``timestamp`` is sampled by the dispatcher (or defaulted to ``now``)
    # so the reducer stays a pure function — see ``ubo_app/utils/clock.py``.
    timestamp: float = field(default_factory=default_now)


class ChatEndSessionAction(ChatAction):
    """End the current chat session and close the chat overlay."""


class ChatAddMessageAction(ChatAction):
    """Append a message to the current chat session."""

    message: ChatMessage
    timestamp: float = field(default_factory=default_now)


class ChatAppendToMessageAction(ChatAction):
    """Append a chunk of streamed text to an existing message.

    Used to stream an assistant (or transcribed user) response into a
    speech bubble chunk-by-chunk as the text arrives.
    """

    message_id: str
    chunk: str
    timestamp: float = field(default_factory=default_now)


class ChatSetMessageTextAction(ChatAction):
    """Replace an existing message's text wholesale.

    Used for cumulative updates where each frame carries the full text so
    far (e.g. STT interim hypotheses, which the recognizer may revise) —
    not deltas. LLM streaming, which is delta-based, continues to use
    ``ChatAppendToMessageAction``.
    """

    message_id: str
    text: str
    timestamp: float = field(default_factory=default_now)


class ChatSendUserMessageAction(ChatAction):
    """A user composed and sent a text message.

    The reducer turns this into a USER ``ChatMessage`` and emits
    ``ChatUserMessageSentEvent`` — the seam a responder listens on.
    """

    text: str
    message_id: str | None = None
    timestamp: float = field(default_factory=default_now)


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


class ChatUserMessageSentEvent(ChatEvent):
    """Emitted after a user message is appended to the conversation.

    A responder listens on this to reply — the echo handler now, the
    assistant service in phase 2.
    """

    text: str
    message_id: str
