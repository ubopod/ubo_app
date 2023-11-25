# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.sound import (
    SoundAction,
    SoundDevice,
    SoundSetMuteStatusAction,
    SoundSetMuteStatusActionPayload,
    SoundState,
)
from ubo_app.store.status_icons import (
    IconRegistrationAction,
    IconRegistrationActionPayload,
)

Action = InitAction | SoundAction | IconRegistrationAction


def reducer(
    state: SoundState | None,
    action: Action,
) -> ReducerResult[SoundState, Action]:
    if state is None:
        if action.type == 'INIT':
            return SoundState(
                output_volume=0.5,
                is_output_mute=False,
                mic_volume=0.5,
                is_mic_mute=False,
            )
        raise InitializationActionError

    if action.type == 'SOUND_SET_VOLUME':
        if action.payload.device == SoundDevice.OUTPUT:
            return replace(state, output_volume=action.payload.volume)
        if action.payload.device == SoundDevice.INPUT:
            return replace(state, input_volume=action.payload.volume)
    elif action.type == 'SOUND_CHANGE_VOLUME':
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
    elif action.type == 'SOUND_SET_MUTE_STATUS':
        if action.payload.device == SoundDevice.OUTPUT:
            return replace(state, is_output_mute=action.payload.mute)
        if action.payload.device == SoundDevice.INPUT:
            return CompleteReducerResult(
                state=replace(state, is_mic_mute=action.payload.mute),
                actions=[
                    IconRegistrationAction(
                        payload=IconRegistrationActionPayload(
                            icon='mic_off' if action.payload.mute else 'mic',
                            priority=-2,
                            id='sound_mic_status',
                        ),
                    ),
                ],
            )
    elif action.type == 'SOUND_TOGGLE_MUTE_STATUS':
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
