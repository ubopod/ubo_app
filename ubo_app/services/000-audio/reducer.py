# ruff: noqa: D100, D103
from __future__ import annotations

from typing import TYPE_CHECKING

from constants import AUDIO_MIC_STATE_ICON_ID, AUDIO_MIC_STATE_ICON_PRIORITY
from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.colors import RUNNING_COLOR
from ubo_app.store.services.audio import (
    AudioAction,
    AudioChangeVolumeAction,
    AudioDevice,
    AudioEvent,
    AudioInstallDriverAction,
    AudioInstallDriverEvent,
    AudioOutput,
    AudioOutputVolume,
    AudioPlayAudioSampleAction,
    AudioPlayAudioSampleEvent,
    AudioPlayAudioSequenceAction,
    AudioPlayAudioSequenceEvent,
    AudioPlaybackDoneAction,
    AudioPlaybackDoneEvent,
    AudioPlayChimeAction,
    AudioPlayChimeEvent,
    AudioPlayRecordingAction,
    AudioReportLineoutJackAction,
    AudioReportRemoteCaptureAction,
    AudioReportSampleAction,
    AudioReportSampleEvent,
    AudioSelectOutputAction,
    AudioSetLineoutAutoSwitchAction,
    AudioSetMuteStatusAction,
    AudioSetVolumeAction,
    AudioStartRecordingAction,
    AudioState,
    AudioStopPlaybackAction,
    AudioStopPlaybackEvent,
    AudioStopRecordingAction,
    AudioToggleMuteStatusAction,
    AudioToggleRecordingAction,
)
from ubo_app.store.services.notifications import Chime
from ubo_app.store.status_icons.types import StatusIconsRegisterAction

if TYPE_CHECKING:
    from collections.abc import Sequence

Action = InitAction | AudioAction | StatusIconsRegisterAction


def _microphone_icon(
    *,
    is_mute: bool,
    is_remote_capture_active: bool,
) -> StatusIconsRegisterAction:
    """Compose the one microphone status icon from everything that affects it.

    Built in a single place so the glyph always tracks the mute state and the
    icon keeps one identity (and therefore one position) no matter which service
    is currently receiving the microphone. A muted microphone is never coloured
    as live: the reducer emits no sample events while muted, so nothing is
    reaching a remote client.
    """
    return StatusIconsRegisterAction(
        icon='󰍭' if is_mute else '󰍬',
        color=RUNNING_COLOR if is_remote_capture_active and not is_mute else 'white',
        priority=AUDIO_MIC_STATE_ICON_PRIORITY,
        id=AUDIO_MIC_STATE_ICON_ID,
    )


def _remember_volume(
    output_volumes: Sequence[AudioOutputVolume],
    output: AudioOutput,
    volume: float,
) -> tuple[AudioOutputVolume, ...]:
    """Return ``output_volumes`` with ``output``'s entry set to ``volume``."""
    return (
        # `==`, not `is`: these come back from the persistent store as
        # freshly-constructed members, so identity comparison silently fails.
        *(item for item in output_volumes if item.output != output),
        AudioOutputVolume(output=output, volume=volume),
    )


def _recall_volume(
    output_volumes: Sequence[AudioOutputVolume],
    output: AudioOutput,
    default: float,
) -> float:
    """Return the volume remembered for ``output``, or ``default``."""
    return next(
        (item.volume for item in output_volumes if item.output == output),
        default,
    )


def reducer(
    state: AudioState | None,
    action: Action,
) -> ReducerResult[AudioState, Action, AudioEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return AudioState()
        raise InitializationActionError(action)

    match action:
        case AudioInstallDriverAction():
            return CompleteReducerResult(
                state=state,
                events=[AudioInstallDriverEvent()],
            )

        case AudioSetVolumeAction(device=AudioDevice.OUTPUT):
            if action.volume == state.playback_volume:
                return state
            return CompleteReducerResult(
                state=state(playback_volume=action.volume),
                events=[AudioPlayChimeEvent(name=Chime.VOLUME_CHANGE)],
            )

        case AudioSetVolumeAction(device=AudioDevice.INPUT):
            return state(capture_volume=action.volume)

        case AudioSelectOutputAction():
            # Bank the level the user set for the output they're leaving, then
            # restore whatever the incoming one was last used at. The speaker
            # and lineout amps have different gain, and a TV has its own volume
            # control downstream, so one shared level is wrong for all three.
            output_volumes = _remember_volume(
                state.output_volumes,
                state.selected_output,
                state.playback_volume,
            )
            return state(
                selected_output=action.output,
                output_volumes=output_volumes,
                playback_volume=_recall_volume(
                    output_volumes,
                    action.output,
                    state.playback_volume,
                ),
            )

        case AudioSetLineoutAutoSwitchAction():
            if not action.is_enabled:
                return state(is_lineout_auto_switch_enabled=False)
            # Turning it on applies it right away rather than waiting for the
            # next plug event, so the toggle has a visible effect.
            return CompleteReducerResult(
                state=state(is_lineout_auto_switch_enabled=True),
                actions=[
                    AudioSelectOutputAction(
                        output=AudioOutput.LINEOUT
                        if state.is_lineout_jack_inserted
                        else AudioOutput.UBO_SPEAKERS,
                    ),
                ],
            )

        case AudioReportLineoutJackAction():
            # Only *transitions* drive automatic switching. Re-reporting the
            # current level (on startup, or a repeated edge) must not undo a
            # manual selection the user made since the jack last moved.
            if action.is_inserted == state.is_lineout_jack_inserted:
                return state
            new_state = state(is_lineout_jack_inserted=action.is_inserted)
            if not new_state.is_lineout_auto_switch_enabled:
                return new_state
            return CompleteReducerResult(
                state=new_state,
                actions=[
                    AudioSelectOutputAction(
                        output=AudioOutput.LINEOUT
                        if action.is_inserted
                        else AudioOutput.UBO_SPEAKERS,
                    ),
                ],
            )

        case AudioChangeVolumeAction(device=AudioDevice.OUTPUT):
            return CompleteReducerResult(
                state=state,
                actions=[
                    AudioSetVolumeAction(
                        device=AudioDevice.OUTPUT,
                        volume=min(
                            max(state.playback_volume + action.amount, 0),
                            1,
                        ),
                    ),
                ],
            )

        case AudioChangeVolumeAction(device=AudioDevice.INPUT):
            return state(
                capture_volume=min(
                    max(state.capture_volume + action.amount, 0),
                    1,
                ),
            )

        case AudioSetMuteStatusAction(device=AudioDevice.OUTPUT):
            return state(is_playback_mute=action.is_mute)

        case AudioSetMuteStatusAction(device=AudioDevice.INPUT):
            return CompleteReducerResult(
                state=state(is_capture_mute=action.is_mute),
                actions=[
                    _microphone_icon(
                        is_mute=action.is_mute,
                        is_remote_capture_active=state.is_remote_capture_active,
                    ),
                ],
            )

        case AudioReportRemoteCaptureAction(is_active=is_active):
            return CompleteReducerResult(
                state=state(is_remote_capture_active=is_active),
                actions=[
                    _microphone_icon(
                        is_mute=state.is_capture_mute,
                        is_remote_capture_active=is_active,
                    ),
                ],
            )

        case AudioToggleMuteStatusAction():
            return CompleteReducerResult(
                state=state,
                actions=[
                    AudioSetMuteStatusAction(
                        is_mute=not state.is_playback_mute
                        if action.device == AudioDevice.OUTPUT
                        else not state.is_capture_mute,
                        device=action.device,
                    ),
                ],
            )

        case AudioPlayChimeAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    AudioPlayChimeEvent(name=action.name),
                ],
            )

        case AudioPlayAudioSequenceAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    AudioPlayAudioSequenceEvent(
                        volume=state.playback_volume,
                        sample=action.sample,
                        id=action.id,
                        index=action.index,
                        source=action.source,
                    ),
                ],
            )

        case AudioStopPlaybackAction():
            return CompleteReducerResult(
                state=state,
                events=[AudioStopPlaybackEvent()],
            )

        case AudioPlayAudioSampleAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    AudioPlayAudioSampleEvent(
                        volume=state.playback_volume,
                        sample=action.sample,
                    ),
                ],
            )

        case AudioPlaybackDoneAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    AudioPlaybackDoneEvent(id=action.id),
                ],
            )

        case AudioReportSampleAction():
            return CompleteReducerResult(
                state=state(
                    recording=action.sample()
                    if state.recording is None
                    else state.recording(
                        data=state.recording.data + action.sample.data,
                    ),
                )
                if state.is_recording
                else state,
                events=[]
                if state.is_capture_mute
                else [
                    AudioReportSampleEvent(
                        timestamp=action.timestamp,
                        sample=action.sample,
                        sample_speech_recognition=action.sample_speech_recognition,
                        audio_source=action.audio_source,
                    ),
                ],
            )

        case AudioStartRecordingAction():
            return state(is_recording=True, recording=None)

        case AudioStopRecordingAction():
            return state(is_recording=False)

        case AudioToggleRecordingAction():
            return CompleteReducerResult(
                state=state,
                actions=[
                    AudioStopRecordingAction()
                    if state.is_recording
                    else AudioStartRecordingAction(),
                ],
            )

        case AudioPlayRecordingAction() if state.recording and not state.is_recording:
            return CompleteReducerResult(
                state=state,
                events=[
                    AudioPlayAudioSampleEvent(sample=state.recording, volume=1),
                ],
            )

        case _:
            return state
