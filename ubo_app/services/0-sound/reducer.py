# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

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
    SoundSetMuteStatusActionPayload,
    SoundSetVolumeAction,
    SoundState,
    SoundToggleMuteStatusAction,
)
from ubo_app.store.status_icons import (
    StatusIconsRegisterAction,
    StatusIconsRegisterActionPayload,
)

Action = InitAction | SoundAction | StatusIconsRegisterAction


def reducer(
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
        if action.payload.device == SoundDevice.OUTPUT:
            return replace(state, output_volume=action.payload.volume)
        if action.payload.device == SoundDevice.INPUT:
            return replace(state, input_volume=action.payload.volume)
    elif isinstance(action, SoundChangeVolumeAction):
        if action.payload.device == SoundDevice.OUTPUT:
            return replace(
                state,
                output_volume=min(
                    max(state.output_volume + action.payload.amount, 0),
                    1,
                ),
            )
        if action.payload.device == SoundDevice.INPUT:
            return replace(
                state,
                input_volume=min(
                    max(state.mic_volume + action.payload.amount, 0),
                    1,
                ),
            )
    elif isinstance(action, SoundSetMuteStatusAction):
        if action.payload.device == SoundDevice.OUTPUT:
            return replace(state, is_output_mute=action.payload.mute)
        if action.payload.device == SoundDevice.INPUT:
            return CompleteReducerResult(
                state=replace(state, is_mic_mute=action.payload.mute),
                actions=[
                    StatusIconsRegisterAction(
                        payload=StatusIconsRegisterActionPayload(
                            icon='mic_off' if action.payload.mute else 'mic',
                            priority=-2,
                            id='sound_mic_status',
                        ),
                    ),
                ],
            )
    elif isinstance(action, SoundToggleMuteStatusAction):
        return CompleteReducerResult(
            state=state,
            actions=[
                SoundSetMuteStatusAction(
                    payload=SoundSetMuteStatusActionPayload(
                        mute=not state.is_output_mute
                        if action.payload.device == SoundDevice.OUTPUT
                        else not state.is_mic_mute,
                        device=action.payload.device,
                    ),
                ),
            ],
        )
    return state
