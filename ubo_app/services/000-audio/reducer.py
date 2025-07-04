# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from constants import AUDIO_MIC_STATE_ICON_ID, AUDIO_MIC_STATE_ICON_PRIORITY
from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.audio import (
    AudioAction,
    AudioChangeVolumeAction,
    AudioDevice,
    AudioEvent,
    AudioInstallDriverAction,
    AudioInstallDriverEvent,
    AudioPlayAudioSampleAction,
    AudioPlayAudioSampleEvent,
    AudioPlayAudioSequenceAction,
    AudioPlayAudioSequenceEvent,
    AudioPlaybackDoneAction,
    AudioPlaybackDoneEvent,
    AudioPlayChimeAction,
    AudioPlayChimeEvent,
    AudioSetMuteStatusAction,
    AudioSetVolumeAction,
    AudioState,
    AudioToggleMuteStatusAction,
)
from ubo_app.store.services.notifications import Chime
from ubo_app.store.status_icons.types import StatusIconsRegisterAction

Action = InitAction | AudioAction | StatusIconsRegisterAction


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
            return replace(state, playback_volume=action.volume)

        case AudioSetVolumeAction(device=AudioDevice.INPUT):
            return replace(state, capture_volume=action.volume)

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
                events=[AudioPlayChimeEvent(name=Chime.VOLUME_CHANGE)],
            )

        case AudioChangeVolumeAction(device=AudioDevice.INPUT):
            return replace(
                state,
                capture_volume=min(
                    max(state.capture_volume + action.amount, 0),
                    1,
                ),
            )

        case AudioSetMuteStatusAction(device=AudioDevice.OUTPUT):
            return replace(state, is_playback_mute=action.is_mute)

        case AudioSetMuteStatusAction(device=AudioDevice.INPUT):
            return CompleteReducerResult(
                state=replace(state, is_capture_mute=action.is_mute),
                actions=[
                    StatusIconsRegisterAction(
                        icon='󰍭' if action.is_mute else '󰍬',
                        priority=AUDIO_MIC_STATE_ICON_PRIORITY,
                        id=AUDIO_MIC_STATE_ICON_ID,
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
                    ),
                ],
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

        case _:
            return state
