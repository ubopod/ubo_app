# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from constants import SOUND_MIC_STATE_ICON_ID, SOUND_MIC_STATE_ICON_PRIORITY
from redux import (
    BaseEvent,
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.sound import (
    SoundAction,
    SoundChangeVolumeAction,
    SoundDevice,
    SoundSetMuteStatusAction,
    SoundSetVolumeAction,
    SoundState,
    SoundToggleMuteStatusAction,
)
from ubo_app.store.status_icons import (
    StatusIconsRegisterAction,
)

Action = InitAction | SoundAction | StatusIconsRegisterAction


def reducer(  # noqa: C901
    state: SoundState | None,
    action: Action,
) -> ReducerResult[SoundState, Action, BaseEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return SoundState(
                output_volume=0.5,
                is_output_mute=False,
                mic_volume=0.5,
                is_mic_mute=False,
            )
        raise InitializationActionError

    if isinstance(action, SoundSetVolumeAction):
        if action.device == SoundDevice.OUTPUT:
            return replace(state, output_volume=action.volume)
        if action.device == SoundDevice.INPUT:
            return replace(state, input_volume=action.volume)
    elif isinstance(action, SoundChangeVolumeAction):
        if action.device == SoundDevice.OUTPUT:
            return replace(
                state,
                output_volume=min(
                    max(state.output_volume + action.amount, 0),
                    1,
                ),
            )
        if action.device == SoundDevice.INPUT:
            return replace(
                state,
                input_volume=min(
                    max(state.mic_volume + action.amount, 0),
                    1,
                ),
            )
    elif isinstance(action, SoundSetMuteStatusAction):
        if action.device == SoundDevice.OUTPUT:
            return replace(state, is_output_mute=action.mute)
        if action.device == SoundDevice.INPUT:
            return CompleteReducerResult(
                state=replace(state, is_mic_mute=action.mute),
                actions=[
                    StatusIconsRegisterAction(
                        icon='mic_off' if action.mute else 'mic',
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
                    mute=not state.is_output_mute
                    if action.device == SoundDevice.OUTPUT
                    else not state.is_mic_mute,
                    device=action.device,
                ),
            ],
        )
    return state
