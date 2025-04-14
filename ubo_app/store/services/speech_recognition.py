# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import field

from immutable import Immutable
from redux import BaseAction

from ubo_app.utils.persistent_store import read_from_persistent_store


class SpeechRecognitionAction(BaseAction): ...


class SpeechRecognitionSetIsActiveAction(SpeechRecognitionAction):
    is_active: bool


class SpeechRecognitionState(Immutable):
    is_active: bool = field(
        default_factory=lambda: read_from_persistent_store(
            'speech_recognition:is_active',
            default=True,
        ),
    )
