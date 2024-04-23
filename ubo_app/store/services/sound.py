# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

import functools
from dataclasses import field
from enum import StrEnum
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.persistent_store import read_from_persistent_store

if TYPE_CHECKING:
    from collections.abc import Sequence


class SoundDevice(StrEnum):
    INPUT = 'Input'
    OUTPUT = 'Output'


class SoundAction(BaseAction): ...


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


class SoundPlayAudioAction(SoundAction):
    sample: Sequence[int]
    channels: int
    rate: int
    width: int


class SoundEvent(BaseEvent): ...


class SoundPlayChimeEvent(SoundEvent):
    name: str


class SoundPlayAudioEvent(SoundEvent):
    sample: Sequence[int]
    channels: int
    rate: int
    width: int


class SoundState(Immutable):
    playback_volume: float = field(
        default_factory=functools.partial(
            read_from_persistent_store,
            key='sound_playback_volume',
            object_type=float,
            default=0.5,
        ),
    )
    is_playback_mute: bool = field(
        default_factory=functools.partial(
            read_from_persistent_store,
            key='sound_is_playback_mute',
            object_type=bool,
            default=False,
        ),
    )
    capture_volume: float = field(
        default_factory=functools.partial(
            read_from_persistent_store,
            key='sound_capture_volume',
            object_type=float,
            default=0.5,
        ),
    )
    is_capture_mute: bool = field(
        default_factory=functools.partial(
            read_from_persistent_store,
            key='sound_is_capture_mute',
            object_type=bool,
            default=False,
        ),
    )
