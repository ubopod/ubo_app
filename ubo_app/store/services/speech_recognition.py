"""Definitions for speech recognition service actions, events and state."""

from __future__ import annotations

from dataclasses import field
from enum import StrEnum

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.persistent_store import read_from_persistent_store


class SpeechRecognitionAction(BaseAction):
    """Base class for speech recognition actions."""


class SpeechRecognitionSetSelectedEngineAction(SpeechRecognitionAction):
    """Action to set the selected speech recognition engine."""

    engine_name: SpeechRecognitionEngineName | None


class SpeechRecognitionSetIsIntentsActiveAction(SpeechRecognitionAction):
    """Action to set the active state of the voice intents listener."""

    is_active: bool


class SpeechRecognitionSetIsAssistantActiveAction(SpeechRecognitionAction):
    """Action to set the active state of the voice assistant listener."""

    is_active: bool


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
    is_intents_active: bool = field(
        default=read_from_persistent_store(
            'speech_recognition:is_intents_active',
            default=True,
        ),
    )
    is_assistant_active: bool = field(
        default=read_from_persistent_store(
            'speech_recognition:is_assistant_active',
            default=False,
        ),
    )
    status: SpeechRecognitionStatus = SpeechRecognitionStatus.IDLE
