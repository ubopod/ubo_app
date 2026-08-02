"""Definition of audio state, actions, and events."""

from __future__ import annotations

from dataclasses import field
from enum import StrEnum

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.clock import default_now
from ubo_app.utils.persistent_store import read_from_persistent_store


class AudioDevice(StrEnum):
    """Audio device enum."""

    INPUT = 'Input'
    OUTPUT = 'Output'


class AudioSequenceSource(StrEnum):
    """Origin of an :class:`AudioPlayAudioSequenceAction`.

    Consumers that only care about a particular producer (currently: the chat
    overlay, which needs to stay open while the live assistant pipeline is
    playing TTS) match on this enum instead of parsing the free-form ``id``.
    Defaults to :attr:`OTHER` so existing producers — chimes, file-system
    playback, one-shot ``assistant_request`` synthesis — keep their current
    "don't affect chat" semantics.
    """

    OTHER = 'other'
    ASSISTANT_LIVE = 'assistant_live'


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


class AudioReportRemoteCaptureAction(AudioAction):
    """Report whether a remote client is set up to receive the microphone.

    Dispatched by services that stream the device microphone off-device (the
    Wyoming satellite today). It only colours the microphone status icon — the
    audio service stays the single owner of that icon, so there is one
    microphone indicator whose glyph always tracks the mute state and whose
    position never depends on which other service happens to be running.
    """

    is_active: bool


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
    source: AudioSequenceSource = AudioSequenceSource.OTHER


class AudioSample(Immutable):
    """An audio sample."""

    data: bytes
    channels: int
    rate: int
    width: int


class AudioReportSampleAction(AudioAction):
    """Report audio sample action."""

    timestamp: float
    sample_speech_recognition: bytes
    sample: AudioSample
    audio_source: str = ''
    """Origin of the sample. Empty string = on-device system mic; remote clients
    (browser, mobile) set a unique id so a listening session can bind to one."""


class AudioPlaybackDoneAction(AudioAction):
    """Playback done action."""

    id: str
    source: AudioSequenceSource = AudioSequenceSource.OTHER
    # Anchors the chat overlay's idle-dismiss countdown — sampled by the
    # audio service's play loop when the buffer drains, not by the
    # consumer reducer (keeps the reducer pure).
    timestamp: float = field(default_factory=default_now)


class AudioStartRecordingAction(AudioAction):
    """Start recording action."""


class AudioStopPlaybackAction(AudioAction):
    """Stop all audio playback."""


class AudioStopRecordingAction(AudioAction):
    """Stop recording action."""


class AudioToggleRecordingAction(AudioAction):
    """toggle recording action."""


class AudioPlayRecordingAction(AudioAction):
    """Play recording action."""


class AudioEvent(BaseEvent):
    """Audio event."""


class AudioReportSampleEvent(AudioEvent):
    """Report audio sample event."""

    timestamp: float
    sample_speech_recognition: bytes
    sample: AudioSample
    audio_source: str = ''
    """Origin of the sample, copied from the action. Empty string = system mic."""


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
    source: AudioSequenceSource = AudioSequenceSource.OTHER


class AudioStopPlaybackEvent(AudioEvent):
    """Stop all audio playback event."""


class AudioPlaybackDoneEvent(AudioEvent):
    """Playback done event."""

    id: str


def _capture_mute_default() -> bool:
    """Return the default capture mute state.

    On non-RPi (e.g. macOS), always start with mic unmuted since there is no
    hardware mute switch. On RPi, restore the persisted state.
    """
    from ubo_app.utils import IS_RPI

    if not IS_RPI:
        return False
    return read_from_persistent_store(
        'audio_state:is_capture_mute',
        default=True,
    )


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
        default=_capture_mute_default(),
    )

    # Whether a remote client is receiving the microphone (e.g. the Wyoming
    # satellite). Colours the microphone status icon; not persisted, since it
    # describes a live connection rather than user intent.
    is_remote_capture_active: bool = False

    is_recording: bool = False
    recording: AudioSample | None = None
