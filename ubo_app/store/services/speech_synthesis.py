# ruff: noqa: D100, D101
from __future__ import annotations

import socket
from dataclasses import field
from enum import StrEnum

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.dataclass import default_provider
from ubo_app.utils.persistent_store import read_from_persistent_store


class SpeechSynthesisAction(BaseAction): ...


class SpeechSynthesisEvent(BaseEvent): ...


class SpeechSynthesisEngineName(StrEnum):
    PIPER = 'piper'
    PICOVOICE = 'picovoice'


class ReadableInformation(Immutable):
    text: str
    piper_text: str = field(
        default_factory=default_provider(
            ['text'],
            lambda text: text.replace('{{hostname}}', f'{socket.gethostname()}.local'),
        ),
    )
    picovoice_text: str = field(
        default_factory=default_provider(
            ['text'],
            lambda text: text.replace('{{hostname}}', f'{socket.gethostname()}.local'),
        ),
    )

    def __post_init__(self) -> None:
        """Replace `{{hostname}}` with the current hostname."""
        object.__setattr__(
            self,
            'text',
            self.text.replace(
                '{{hostname}}',
                f'{socket.gethostname()}.local',
            ),
        )

    def __add__(
        self,
        other: ReadableInformation,
    ) -> ReadableInformation:
        """Concatenate two `ReadableInformation` objects."""
        return ReadableInformation(
            text=self.text + other.text,
            piper_text=self.piper_text + other.piper_text,
            picovoice_text=self.picovoice_text + other.picovoice_text,
        )


class SpeechSynthesisReadTextAction(SpeechSynthesisAction):
    information: ReadableInformation
    # `speech_rate` and `engine` are deprecated no-ops, kept for backward
    # compatibility with external/generated clients. Synthesis is now performed
    # by the assistant's TTS pipeline, which has no per-request rate knob and
    # selects its own provider.
    speech_rate: float | None = None
    engine: SpeechSynthesisEngineName | None = None


class SpeechSynthesisSetIsEnabledAction(SpeechSynthesisAction):
    is_enabled: bool


class SpeechSynthesisSetPreferLocalAction(SpeechSynthesisAction):
    is_enabled: bool


class SpeechSynthesisSynthesizeTextEvent(SpeechSynthesisEvent):
    information: ReadableInformation


class SpeechSynthesisState(Immutable):
    is_screen_reader_enabled: bool = field(
        default_factory=lambda: read_from_persistent_store(
            key='speech_synthesis:is_screen_reader_enabled',
            default=False,
        ),
    )
    # When enabled, the screen reader prefers a configured local TTS engine
    # (Piper, then Kokoro) over the assistant's selected default, which may be
    # cloud-based. When disabled, it uses the assistant's default TTS.
    is_prefer_local_enabled: bool = field(
        default_factory=lambda: read_from_persistent_store(
            key='speech_synthesis:is_prefer_local_enabled',
            default=False,
        ),
    )
