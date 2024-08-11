# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import field
from enum import StrEnum

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.persistent_store import read_from_persistent_store


class VoiceAction(BaseAction): ...


class VoiceEvent(BaseEvent): ...


class VoiceUpdateAccessKeyStatus(VoiceAction):
    is_access_key_set: bool


class VoiceEngine(StrEnum):
    PIPER = 'piper'
    PICOVOICE = 'picovoice'


class VoiceSetEngineAction(VoiceAction):
    engine: VoiceEngine


class VoiceReadTextAction(VoiceAction):
    text: str
    piper_text: str | None = None
    picovoice_text: str | None = None
    speech_rate: float | None = None
    engine: VoiceEngine | None = None


class VoiceSynthesizeTextEvent(VoiceEvent):
    text: str
    piper_text: str
    picovoice_text: str
    speech_rate: float | None = None


class VoiceState(Immutable):
    is_access_key_set: bool | None = None
    selected_engine: VoiceEngine = field(
        default_factory=lambda: read_from_persistent_store(
            key='voice_engine',
            default=VoiceEngine.PIPER,
        ),
    )
