# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from constants import SOUND_MIC_STATE_ICON_ID, SOUND_MIC_STATE_ICON_PRIORITY
from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.notifications import Chime
from ubo_app.store.services.sound import (
    SoundAction,
    SoundChangeVolumeAction,
    SoundDevice,
    SoundEvent,
    SoundPlayAudioAction,
    SoundPlayAudioEvent,
    SoundPlayChimeAction,
    SoundPlayChimeEvent,
    SoundSetMuteStatusAction,
    SoundSetVolumeAction,
    SoundState,
    SoundToggleMuteStatusAction,
)
from ubo_app.store.status_icons import StatusIconsRegisterAction

Action = InitAction | SoundAction | StatusIconsRegisterAction


def reducer(
    state: SoundState | None,
    action: Action,
) -> ReducerResult[SoundState, Action, SoundEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return SoundState()
        raise InitializationActionError(action)

    if isinstance(action, SoundSetVolumeAction):
        if action.device == SoundDevice.OUTPUT:
            return CompleteReducerResult(
                state=replace(state, playback_volume=action.volume),
                events=[
                    SoundPlayChimeEvent(name=Chime.VOLUME_CHANGE),
                ],
            )
        if action.device == SoundDevice.INPUT:
            return replace(state, capture_volume=action.volume)
    elif isinstance(action, SoundChangeVolumeAction):
        if action.device == SoundDevice.OUTPUT:
            return CompleteReducerResult(
                state=state,
                actions=[
                    SoundSetVolumeAction(
                        device=SoundDevice.OUTPUT,
                        volume=min(
                            max(state.playback_volume + action.amount, 0),
                            1,
                        ),
                    ),
                ],
            )
        if action.device == SoundDevice.INPUT:
            return replace(
                state,
                capture_volume=min(
                    max(state.capture_volume + action.amount, 0),
                    1,
                ),
            )
    elif isinstance(action, SoundSetMuteStatusAction):
        if action.device == SoundDevice.OUTPUT:
            return replace(state, is_playback_mute=action.mute)
        if action.device == SoundDevice.INPUT:
            return CompleteReducerResult(
                state=replace(state, is_capture_mute=action.mute),
                actions=[
                    StatusIconsRegisterAction(
                        icon='󰍭' if action.mute else '󰍬',
                        priority=SOUND_MIC_STATE_ICON_PRIORITY,
                        id=SOUND_MIC_STATE_ICON_ID,
                    ),
                ],
            )
    elif isinstance(action, SoundToggleMuteStatusAction):
        return CompleteReducerResult(
            state=state,
            actions=[
                SoundSetMuteStatusAction(
                    mute=not state.is_playback_mute
                    if action.device == SoundDevice.OUTPUT
                    else not state.is_capture_mute,
                    device=action.device,
                ),
            ],
        )
    elif isinstance(action, SoundPlayChimeAction):
        return CompleteReducerResult(
            state=state,
            events=[
                SoundPlayChimeEvent(name=action.name),
            ],
        )
    elif isinstance(action, SoundPlayAudioAction):
        return CompleteReducerResult(
            state=state,
            events=[
                SoundPlayAudioEvent(
                    sample=action.sample,
                    channels=action.channels,
                    rate=action.rate,
                    width=action.width,
                ),
            ],
        )
    return state
