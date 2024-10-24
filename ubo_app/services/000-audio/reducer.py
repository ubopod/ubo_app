# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
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
    AudioPlayAudioAction,
    AudioPlayAudioEvent,
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
from ubo_app.store.status_icons import StatusIconsRegisterAction

Action = InitAction | AudioAction | StatusIconsRegisterAction


def reducer(
    state: AudioState | None,
    action: Action,
) -> ReducerResult[AudioState, Action, AudioEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return AudioState()
        raise InitializationActionError(action)

    if isinstance(action, AudioSetVolumeAction):
        if action.device == AudioDevice.OUTPUT:
            return replace(state, playback_volume=action.volume)
        if action.device == AudioDevice.INPUT:
            return replace(state, capture_volume=action.volume)
    elif isinstance(action, AudioChangeVolumeAction):
        if action.device == AudioDevice.OUTPUT:
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
        if action.device == AudioDevice.INPUT:
            return replace(
                state,
                capture_volume=min(
                    max(state.capture_volume + action.amount, 0),
                    1,
                ),
            )
    elif isinstance(action, AudioSetMuteStatusAction):
        if action.device == AudioDevice.OUTPUT:
            return replace(state, is_playback_mute=action.is_mute)
        if action.device == AudioDevice.INPUT:
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
    elif isinstance(action, AudioToggleMuteStatusAction):
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
    elif isinstance(action, AudioPlayChimeAction):
        return CompleteReducerResult(
            state=state,
            events=[
                AudioPlayChimeEvent(name=action.name),
            ],
        )
    elif isinstance(action, AudioPlayAudioAction):
        return CompleteReducerResult(
            state=state,
            events=[
                AudioPlayAudioEvent(
                    sample=action.sample,
                    channels=action.channels,
                    rate=action.rate,
                    width=action.width,
                    id=action.id,
                ),
            ],
        )
    elif isinstance(action, AudioPlaybackDoneAction):
        return CompleteReducerResult(
            state=state,
            events=[
                AudioPlaybackDoneEvent(id=action.id),
            ],
        )
    return state
