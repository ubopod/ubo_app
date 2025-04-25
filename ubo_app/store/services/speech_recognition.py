"""Definitions for speech recognition service actions, events and state."""

from __future__ import annotations

from dataclasses import field
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ubo_app.store.main import UboAction

from ubo_app.utils.persistent_store import read_from_persistent_store


class SpeechRecognitionAction(BaseAction):
    """Base class for speech recognition actions."""


class SpeechRecognitionSetIsActiveAction(SpeechRecognitionAction):
    """Action to set the active state of speech recognition."""

    is_active: bool


class SpeechRecognitionIntent(Immutable):
    """Intent for speech recognition service."""

    phrase: str | Sequence[str]
    action: UboAction | Sequence[UboAction]


class SpeechRecognitionReportWakeWordDetectionAction(SpeechRecognitionAction):
    """Action to report wake word detection."""


class SpeechRecognitionReportIntentDetectionAction(SpeechRecognitionAction):
    """Action to report intent detection."""

    intent: SpeechRecognitionIntent


class SpeechRecognitionState(Immutable):
    """State for speech recognition service."""

    intents: list[SpeechRecognitionIntent]
    is_active: bool = field(
        default_factory=lambda: read_from_persistent_store(
            'speech_recognition:is_active',
            default=True,
        ),
    )
    is_waiting: bool = False
