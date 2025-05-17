# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
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


class SpeechSynthesisUpdateAccessKeyStatus(SpeechSynthesisAction):
    is_access_key_set: bool


class SpeechSynthesisEngine(StrEnum):
    PIPER = 'piper'
    PICOVOICE = 'picovoice'


class SpeechSynthesisSetEngineAction(SpeechSynthesisAction):
    engine: SpeechSynthesisEngine


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
    speech_rate: float | None = None
    engine: SpeechSynthesisEngine | None = None


class SpeechSynthesisSynthesizeTextEvent(SpeechSynthesisEvent):
    information: ReadableInformation
    speech_rate: float | None = None


class SpeechSynthesisState(Immutable):
    is_access_key_set: bool | None = None
    selected_engine: SpeechSynthesisEngine = field(
        default_factory=lambda: read_from_persistent_store(
            key='speech_synthesis_engine',
            default=SpeechSynthesisEngine.PIPER,
        ),
    )
