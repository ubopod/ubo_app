# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import socket
import sys
from dataclasses import field
from enum import StrEnum

from immutable import Immutable
from redux import BaseAction, BaseEvent

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


def _default_text() -> str:
    # WARNING: Dirty hack ahead
    # This is to set the default value of `piper_text`/`picovoice_text` based on the
    # provided value of `text`
    parent_frame = sys._getframe().f_back  # noqa: SLF001
    if not parent_frame:
        return ''
    text = parent_frame.f_locals.get('text') or ''
    return text.replace(
        '{{hostname}}',
        f'{socket.gethostname()}.local',
    )


class ReadableInformation(Immutable):
    text: str
    piper_text: str = field(default_factory=_default_text)
    picovoice_text: str = field(default_factory=_default_text)

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
