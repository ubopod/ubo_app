# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import field
from enum import StrEnum

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.persistent_store import read_from_persistent_store


class AudioDevice(StrEnum):
    INPUT = 'Input'
    OUTPUT = 'Output'


class AudioAction(BaseAction): ...


class AudioSetVolumeAction(AudioAction):
    volume: float
    device: AudioDevice


class AudioChangeVolumeAction(AudioAction):
    amount: float
    device: AudioDevice


class AudioSetMuteStatusAction(AudioAction):
    is_mute: bool
    device: AudioDevice


class AudioToggleMuteStatusAction(AudioAction):
    device: AudioDevice


class AudioPlayChimeAction(AudioAction):
    name: str


class AudioPlayAudioAction(AudioAction):
    id: str | None = None
    sample: bytes
    channels: int
    rate: int
    width: int


class AudioPlaybackDoneAction(AudioAction):
    id: str


class AudioEvent(BaseEvent): ...


class AudioPlayChimeEvent(AudioEvent):
    name: str


class AudioPlayAudioEvent(AudioEvent):
    id: str | None = None
    sample: bytes
    channels: int
    rate: int
    width: int


class AudioPlaybackDoneEvent(AudioEvent):
    id: str


class AudioState(Immutable):
    playback_volume: float = field(
        default_factory=lambda: read_from_persistent_store(
            'audio_state:playback_volume',
            default=0.15,
        ),
    )
    is_playback_mute: bool = field(
        default_factory=lambda: read_from_persistent_store(
            'audio_state:is_playback_mute',
            default=False,
        ),
    )
    capture_volume: float = field(
        default_factory=lambda: read_from_persistent_store(
            'audio_state:capture_volume',
            default=0.5,
        ),
    )
    is_capture_mute: bool = field(
        default_factory=lambda: read_from_persistent_store(
            'audio_state:is_capture_mute',
            default=False,
        ),
    )
