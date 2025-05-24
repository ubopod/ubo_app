"""Definitions for speech recognition service actions, events and state."""

from __future__ import annotations

from dataclasses import field
from enum import StrEnum
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.store.main import UboAction

from ubo_app.utils.persistent_store import read_from_persistent_store


class SpeechRecognitionAction(BaseAction):
    """Base class for speech recognition actions."""


class SpeechRecognitionSetIsIntentsActiveAction(SpeechRecognitionAction):
    """Action to set the active state of the voice intents listener."""

    is_active: bool


class SpeechRecognitionSetIsAssistantActiveAction(SpeechRecognitionAction):
    """Action to set the active state of the voice assistant listener."""

    is_active: bool


class SpeechRecognitionIntent(Immutable):
    """Intent for speech recognition service."""

    phrase: str | Sequence[str]
    action: UboAction | Sequence[UboAction]


class SpeechRecognitionReportWakeWordDetectionAction(SpeechRecognitionAction):
    """Action to report wake word detection."""

    wake_word: str


class SpeechRecognitionReportIntentDetectionAction(SpeechRecognitionAction):
    """Action to report intent detection."""

    intent: SpeechRecognitionIntent


class SpeechRecognitionReportSpeechAction(SpeechRecognitionAction):
    """Action to report speech raw audio."""

    text: str
    raw_audio: bytes


class SpeechRecognitionEvent(BaseEvent):
    """Base class for speech recognition events."""


class SpeechRecognitionReportTextEvent(SpeechRecognitionEvent):
    """Event to report stream of recognized text."""

    timestamp: float
    text: str


class SpeechRecognitionStatus(StrEnum):
    """State for speech recognition service."""

    IDLE = 'idle'
    INTENTS_WAITING = 'intents_waiting'
    ASSISTANT_WAITING = 'assistant_waiting'


class SpeechRecognitionState(Immutable):
    """State for speech recognition service."""

    intents: list[SpeechRecognitionIntent]
    is_intents_active: bool = field(
        default_factory=lambda: read_from_persistent_store(
            'speech_recognition:is_intents_active',
            default=True,
        ),
    )
    is_assistant_active: bool = field(
        default_factory=lambda: read_from_persistent_store(
            'speech_recognition:is_assistant_active',
            default=False,
        ),
    )
    status: SpeechRecognitionStatus = SpeechRecognitionStatus.IDLE
