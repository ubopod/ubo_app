# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from immutable import Immutable
from redux import BaseAction, BaseEvent


class VoiceAction(BaseAction): ...


class VoiceEvent(BaseEvent): ...


class VoiceUpdateAccessKeyStatus(VoiceAction):
    is_access_key_set: bool


class VoiceReadTextAction(VoiceAction):
    text: str
    speech_rate: float | None = None


class VoiceSynthesizeTextEvent(VoiceEvent):
    text: str
    speech_rate: float | None = None


class VoiceState(Immutable):
    is_access_key_set: bool | None = None
