# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from enum import StrEnum

from redux import BaseAction, BaseEvent, Immutable


class SoundDevice(StrEnum):
    INPUT = 'Input'
    OUTPUT = 'Output'


class SoundAction(BaseAction):
    ...


class SoundSetVolumeAction(SoundAction):
    volume: float
    device: SoundDevice


class SoundChangeVolumeAction(SoundAction):
    amount: float
    device: SoundDevice


class SoundSetMuteStatusAction(SoundAction):
    mute: bool
    device: SoundDevice


class SoundToggleMuteStatusAction(SoundAction):
    device: SoundDevice


class SoundPlayChimeAction(SoundAction):
    name: str


class SoundEvent(BaseEvent):
    ...


class SoundPlayChimeEvent(SoundEvent):
    name: str


class SoundState(Immutable):
    playback_volume: float
    is_playback_mute: bool
    capture_volume: float
    is_capture_mute: bool
