"""Definition of audio state, actions, and events."""

from __future__ import annotations

from dataclasses import field
from enum import StrEnum

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.persistent_store import read_from_persistent_store


class AudioDevice(StrEnum):
    """Audio device enum."""

    INPUT = 'Input'
    OUTPUT = 'Output'


class AudioAction(BaseAction):
    """Audio action."""


class AudioInstallDriverAction(AudioAction):
    """Install audio driver action."""


class AudioSetVolumeAction(AudioAction):
    """Set volume action."""

    volume: float
    device: AudioDevice


class AudioChangeVolumeAction(AudioAction):
    """Change volume action."""

    amount: float
    device: AudioDevice


class AudioSetMuteStatusAction(AudioAction):
    """Set mute status action."""

    is_mute: bool
    device: AudioDevice


class AudioToggleMuteStatusAction(AudioAction):
    """Toggle mute status action."""

    device: AudioDevice


class AudioPlayChimeAction(AudioAction):
    """Play chime action."""

    name: str


class AudioPlayAudioSampleAction(AudioAction):
    """Play audio action."""

    sample: AudioSample


class AudioPlayAudioSequenceAction(AudioAction):
    """Play indexed audio action."""

    sample: AudioSample | None
    id: str
    index: int


class AudioSample(Immutable):
    """An audio sample."""

    data: bytes
    channels: int
    rate: int
    width: int


class AudioPlaybackDoneAction(AudioAction):
    """Playback done action."""

    id: str


class AudioEvent(BaseEvent):
    """Audio event."""


class AudioReportSampleEvent(AudioEvent):
    """Report audio event."""

    timestamp: float
    sample_speech_recognition: bytes
    sample: AudioSample


class AudioInstallDriverEvent(AudioEvent):
    """Install audio driver event."""


class AudioPlayChimeEvent(AudioEvent):
    """Play chime event."""

    name: str


class AudioPlayAudioSampleEvent(AudioEvent):
    """Play audio event."""

    volume: float
    sample: AudioSample


class AudioPlayAudioSequenceEvent(AudioEvent):
    """Play indexed audio event."""

    volume: float
    sample: AudioSample | None
    id: str
    index: int


class AudioPlaybackDoneEvent(AudioEvent):
    """Playback done event."""

    id: str


class AudioState(Immutable):
    """Audio state."""

    playback_volume: float = field(
        default=read_from_persistent_store(
            'audio_state:playback_volume',
            default=0.15,
        ),
    )
    is_playback_mute: bool = field(
        default=read_from_persistent_store(
            'audio_state:is_playback_mute',
            default=False,
        ),
    )
    capture_volume: float = field(
        default=read_from_persistent_store(
            'audio_state:capture_volume',
            default=0.5,
        ),
    )
    is_capture_mute: bool = field(
        default=read_from_persistent_store(
            'audio_state:is_capture_mute',
            default=False,
        ),
    )
