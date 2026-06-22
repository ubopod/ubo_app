"""Definitions for speech recognition service actions, events and state."""

from __future__ import annotations

import json
from dataclasses import field
from enum import StrEnum

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.constants.assistant import (
    ASSISTANT_CONVERSATION_END_PHRASES,
    ASSISTANT_CONVERSATION_WAKE_WORD,
    ASSISTANT_QUICK_CHAT_WAKE_PHRASE,
    ASSISTANT_STOP_TALKING_PHRASE,
    INTENTS_WAKE_WORD,
)
from ubo_app.utils.persistent_store import read_from_persistent_store


class WakeMode(StrEnum):
    """The four user-editable wake/stop phrase slots.

    Each maps to one :class:`WakeWordSlot` on :class:`SpeechRecognitionState`, and
    discriminates assistant trigger policies without coupling them to the literal
    phrase text. The conversation-end phrases are deliberately *not* a ``WakeMode``
    — they are consumed assistant-side, not detected as a wake word.
    """

    INTENTS = 'intents'
    QUICK_CHAT = 'quick_chat'
    CONVERSATION = 'conversation'
    STOP_TALKING = 'stop_talking'


class SpeechRecognitionAction(BaseAction):
    """Base class for speech recognition actions."""


class SpeechRecognitionSetSelectedEngineAction(SpeechRecognitionAction):
    """Action to set the selected speech recognition engine."""

    engine_name: SpeechRecognitionEngineName | None


class SpeechRecognitionSetSlotEnabledAction(SpeechRecognitionAction):
    """Enable or disable one wake-word slot.

    Conversation and Stop are coupled: setting either updates both (enforced in
    the reducer, so every client honours the invariant).
    """

    mode: WakeMode
    enabled: bool


class SpeechRecognitionSetAssistantSlotsEnabledAction(SpeechRecognitionAction):
    """Enable or disable all assistant wake slots at once.

    Backs the "Assistant: Turn On/Off" voice command — sets quick-chat,
    conversation, and stop together (the command interface / intents slot is
    independent and unaffected).
    """

    enabled: bool


class SpeechRecognitionAddCommandAction(SpeechRecognitionAction):
    """Action to add a custom voice command."""

    id: str
    label: str
    phrases: list[str]
    action_keys: list[str]


class SpeechRecognitionUpdateCommandAction(SpeechRecognitionAction):
    """Action to replace the command with the matching ``id``."""

    id: str
    label: str
    phrases: list[str]
    action_keys: list[str]


class SpeechRecognitionRemoveCommandAction(SpeechRecognitionAction):
    """Action to remove the command with the matching ``id``."""

    id: str


class SpeechRecognitionSetWakePhrasesAction(SpeechRecognitionAction):
    """Replace the phrases of one wake-word slot (a set of alternatives)."""

    mode: WakeMode
    phrases: tuple[str, ...]


class SpeechRecognitionSetConversationEndPhrasesAction(SpeechRecognitionAction):
    """Replace the conversation end-of-turn phrases (a set of alternatives)."""

    phrases: tuple[str, ...]


class SpeechRecognitionIntent(Immutable):
    """A voice command: example phrases mapped to bindable-action keys.

    ``action_keys`` reference entries in the bindable-actions registry
    (:mod:`ubo_app.store.core.bindable_actions`); they are resolved and
    dispatched when one of the ``phrases`` is recognised.
    """

    id: str
    label: str
    phrases: list[str]
    action_keys: list[str]


class SpeechRecognitionReportWakeWordDetectionAction(SpeechRecognitionAction):
    """Action to report wake word detection."""

    wake_word: str
    engine_name: str = ''
    """Name of the engine that detected the phrase (forwarded to consumers)."""


class SpeechRecognitionReportIntentDetectionAction(SpeechRecognitionAction):
    """Action to report intent detection."""

    intent: SpeechRecognitionIntent
    text: str


class SpeechRecognitionReportIntentTimeoutAction(SpeechRecognitionAction):
    """Action reporting that intent listening elapsed without a command."""


class SpeechRecognitionReportSpeechAction(SpeechRecognitionAction):
    """Action to report speech raw audio and recognized text."""

    engine_name: SpeechRecognitionEngineName
    text: str
    audio: bytes


class SpeechRecognitionEvent(BaseEvent):
    """Base class for speech recognition events."""


class SpeechRecognitionReportTextEvent(SpeechRecognitionEvent):
    """Event to report stream of recognized text."""

    timestamp: float
    text: str


class SpeechRecognitionBoundActionTriggeredEvent(SpeechRecognitionEvent):
    """Event emitted when a recognised command's action keys should fire.

    The speech-recognition service's handler resolves each ``action_keys``
    entry against the bindable-actions registry and dispatches the produced
    actions (keeping the reducer pure).
    """

    action_keys: list[str]
    phrase: str


class SpeechRecognitionStatus(StrEnum):
    """State for speech recognition service."""

    IDLE = 'idle'
    INTENTS_WAITING = 'intents_waiting'
    ASSISTANT_WAITING = 'assistant_waiting'


class SpeechRecognitionEngineName(StrEnum):
    """Available speech recognition engines."""

    VOSK = 'vosk'
    GOOGLE = 'google_cloud'


class WakeWordSlot(Immutable):
    """One wake-word category: its alternative phrases and whether it's active."""

    mode: WakeMode
    phrases: tuple[str, ...]
    enabled: bool


# Canonical slot order — indexing and rendering rely on it being stable.
_SLOT_ORDER: tuple[WakeMode, ...] = (
    WakeMode.INTENTS,
    WakeMode.QUICK_CHAT,
    WakeMode.CONVERSATION,
    WakeMode.STOP_TALKING,
)
_DEFAULT_SLOT_PHRASES: dict[WakeMode, tuple[str, ...]] = {
    WakeMode.INTENTS: (INTENTS_WAKE_WORD,),
    WakeMode.QUICK_CHAT: (ASSISTANT_QUICK_CHAT_WAKE_PHRASE,),
    WakeMode.CONVERSATION: (ASSISTANT_CONVERSATION_WAKE_WORD,),
    WakeMode.STOP_TALKING: (ASSISTANT_STOP_TALKING_PHRASE,),
}
# Default activation preserves the Phase-1 behaviour: command interface on,
# the assistant slots off.
_DEFAULT_SLOT_ENABLED: dict[WakeMode, bool] = {
    WakeMode.INTENTS: True,
    WakeMode.QUICK_CHAT: False,
    WakeMode.CONVERSATION: False,
    WakeMode.STOP_TALKING: False,
}


def _default_slot(mode: WakeMode) -> WakeWordSlot:
    return WakeWordSlot(
        mode=mode,
        phrases=_DEFAULT_SLOT_PHRASES[mode],
        enabled=_DEFAULT_SLOT_ENABLED[mode],
    )


def _synthesize_legacy_slots() -> tuple[WakeWordSlot, ...]:
    """Build slots from the Phase-1 persistent keys (one-shot migration).

    Phase 1 stored two activation booleans + four single-phrase keys. When the
    new ``wake_slots`` key is absent we read those so a branch user doesn't lose
    their toggles/phrases on upgrade. The legacy keys then go stale.
    """
    is_intents = read_from_persistent_store(
        'speech_recognition:is_intents_active',
        default=_DEFAULT_SLOT_ENABLED[WakeMode.INTENTS],
    )
    is_assistant = read_from_persistent_store(
        'speech_recognition:is_assistant_active',
        default=False,
    )
    legacy_phrase = {
        WakeMode.INTENTS: read_from_persistent_store(
            'speech_recognition:intents_wake_word',
            default=INTENTS_WAKE_WORD,
        ),
        WakeMode.QUICK_CHAT: read_from_persistent_store(
            'speech_recognition:quick_chat_wake_phrase',
            default=ASSISTANT_QUICK_CHAT_WAKE_PHRASE,
        ),
        WakeMode.CONVERSATION: read_from_persistent_store(
            'speech_recognition:conversation_wake_phrase',
            default=ASSISTANT_CONVERSATION_WAKE_WORD,
        ),
        WakeMode.STOP_TALKING: read_from_persistent_store(
            'speech_recognition:stop_talking_phrase',
            default=ASSISTANT_STOP_TALKING_PHRASE,
        ),
    }
    enabled = {
        WakeMode.INTENTS: bool(is_intents),
        WakeMode.QUICK_CHAT: bool(is_assistant),
        WakeMode.CONVERSATION: bool(is_assistant),
        WakeMode.STOP_TALKING: bool(is_assistant),
    }
    return tuple(
        WakeWordSlot(mode=mode, phrases=(legacy_phrase[mode],), enabled=enabled[mode])
        for mode in _SLOT_ORDER
    )


def _load_wake_slots() -> tuple[WakeWordSlot, ...]:
    """Load wake slots from persistent storage, falling back to defaults.

    Stored as a JSON blob (list of ``{mode, phrases, enabled}``). Missing modes
    fall back to their default; a malformed blob falls back entirely.
    """
    raw = read_from_persistent_store('speech_recognition:wake_slots', default=None)
    if not raw:
        return _synthesize_legacy_slots()
    try:
        entries = {entry['mode']: entry for entry in json.loads(raw)}
    except (json.JSONDecodeError, TypeError, KeyError):
        return tuple(_default_slot(mode) for mode in _SLOT_ORDER)
    slots: list[WakeWordSlot] = []
    for mode in _SLOT_ORDER:
        entry = entries.get(mode.value)
        if not entry:
            slots.append(_default_slot(mode))
            continue
        slots.append(
            WakeWordSlot(
                mode=mode,
                phrases=tuple(entry.get('phrases') or _DEFAULT_SLOT_PHRASES[mode]),
                enabled=bool(entry.get('enabled', _DEFAULT_SLOT_ENABLED[mode])),
            ),
        )
    return tuple(slots)


class SpeechRecognitionState(Immutable):
    """State for speech recognition service."""

    selected_engine: SpeechRecognitionEngineName | None = field(
        default=read_from_persistent_store(
            'speech_recognition:selected_engine',
            mapper=lambda value: SpeechRecognitionEngineName(value)
            if value in SpeechRecognitionEngineName.__members__.values()
            else SpeechRecognitionEngineName.VOSK,
            default=SpeechRecognitionEngineName.VOSK,
        ),
    )
    intents: list[SpeechRecognitionIntent] = field(default_factory=list)
    wake_slots: tuple[WakeWordSlot, ...] = field(default_factory=_load_wake_slots)
    conversation_end_phrases: tuple[str, ...] = field(
        default=read_from_persistent_store(
            'speech_recognition:conversation_end_phrases',
            mapper=tuple,
            default=ASSISTANT_CONVERSATION_END_PHRASES,
        ),
    )
    status: SpeechRecognitionStatus = SpeechRecognitionStatus.IDLE


def slot_for_mode(state: SpeechRecognitionState, mode: WakeMode) -> WakeWordSlot:
    """Return the wake-word slot for *mode*."""
    return next(slot for slot in state.wake_slots if slot.mode is mode)


def phrases_for_mode(state: SpeechRecognitionState, mode: WakeMode) -> tuple[str, ...]:
    """Return the phrases configured for *mode*."""
    return slot_for_mode(state, mode).phrases
