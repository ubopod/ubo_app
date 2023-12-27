# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from enum import StrEnum

from redux import BaseAction, Immutable


class SoundDevice(StrEnum):
    INPUT = 'Input'
    OUTPUT = 'Output'


class SoundSetVolumeAction(BaseAction):
    volume: float
    device: SoundDevice


class SoundChangeVolumeAction(BaseAction):
    amount: float
    device: SoundDevice


class SoundSetMuteStatusAction(BaseAction):
    mute: bool
    device: SoundDevice


class SoundToggleMuteStatusAction(BaseAction):
    device: SoundDevice


SoundAction = (
    SoundSetVolumeAction
    | SoundChangeVolumeAction
    | SoundSetMuteStatusAction
    | SoundToggleMuteStatusAction
)


class SoundState(Immutable):
    output_volume: float
    is_output_mute: bool
    mic_volume: float
    is_mic_mute: bool
