# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from enum import Enum

from redux import BaseAction, Immutable


class SoundDevice(str, Enum):
    INPUT = 'Input'
    OUTPUT = 'Output'


class SoundSetVolumeActionPayload(Immutable):
    volume: float
    device: SoundDevice


class SoundSetVolumeAction(BaseAction):
    payload: SoundSetVolumeActionPayload


class SoundChangeVolumeActionPayload(Immutable):
    amount: float
    device: SoundDevice


class SoundChangeVolumeAction(BaseAction):
    payload: SoundChangeVolumeActionPayload


class SoundSetMuteStatusActionPayload(Immutable):
    mute: bool
    device: SoundDevice


class SoundSetMuteStatusAction(BaseAction):
    payload: SoundSetMuteStatusActionPayload


class SoundToggleMuteStatusActionPayload(Immutable):
    device: SoundDevice


class SoundToggleMuteStatusAction(BaseAction):
    payload: SoundToggleMuteStatusActionPayload


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
