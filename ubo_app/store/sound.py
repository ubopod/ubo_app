# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from enum import Enum
from typing import Literal

from redux import BaseAction, Immutable


class SoundDevice(str, Enum):
    INPUT = 'Input'
    OUTPUT = 'Output'


class SoundSetVolumeActionPayload(Immutable):
    volume: float
    device: SoundDevice


class SoundSetVolumeAction(BaseAction):
    type: Literal['SOUND_SET_VOLUME'] = 'SOUND_SET_VOLUME'
    payload: SoundSetVolumeActionPayload


class SoundChangeVolumeActionPayload(Immutable):
    amount: float
    device: SoundDevice


class SoundChangeVolumeAction(BaseAction):
    type: Literal['SOUND_CHANGE_VOLUME'] = 'SOUND_CHANGE_VOLUME'
    payload: SoundChangeVolumeActionPayload


class SoundSetMuteStatusActionPayload(Immutable):
    mute: bool
    device: SoundDevice


class SoundSetMuteStatusAction(BaseAction):
    type: Literal['SOUND_SET_MUTE_STATUS'] = 'SOUND_SET_MUTE_STATUS'
    payload: SoundSetMuteStatusActionPayload


class SoundToggleMuteStatusActionPayload(Immutable):
    device: SoundDevice


class SoundToggleMuteStatusAction(BaseAction):
    type: Literal['SOUND_TOGGLE_MUTE_STATUS'] = 'SOUND_TOGGLE_MUTE_STATUS'
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
