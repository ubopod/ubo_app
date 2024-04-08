# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.rgb_ring import (
    RgbRingAction,
    RgbRingBlankAction,
    RgbRingBlinkAction,
    RgbRingColorfulCommandAction,
    RgbRingCommandAction,
    RgbRingCommandEvent,
    RgbRingFillDownfromAction,
    RgbRingFillUptoAction,
    RgbRingProgressWheelAction,
    RgbRingProgressWheelStepAction,
    RgbRingPulseAction,
    RgbRingRainbowAction,
    RgbRingSetAllAction,
    RgbRingSetBrightnessAction,
    RgbRingSetEnabledAction,
    RgbRingSetIsBusyAction,
    RgbRingSetIsConnectedAction,
    RgbRingSpinningWheelAction,
    RgbRingState,
)

Action = InitAction | RgbRingAction


def reducer(
    state: RgbRingState | None,
    action: Action,
) -> ReducerResult[RgbRingState, Action, RgbRingCommandEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return RgbRingState(is_connected=True, is_busy=False)
        raise InitializationActionError(action)

    if isinstance(action, RgbRingSetIsConnectedAction):
        return replace(
            state,
            is_connected=action.is_connected,
        )

    if isinstance(action, RgbRingSetIsBusyAction):
        return replace(
            state,
            is_busy=action.is_busy,
        )

    if isinstance(action, RgbRingCommandAction):
        command = None

        if isinstance(action, RgbRingColorfulCommandAction):
            (r, g, b, *_) = action.color
            if isinstance(action, RgbRingSetAllAction):
                command = f'set_all {r} {g} {b}'
            elif isinstance(action, RgbRingBlinkAction):
                command = f'blink {r} {g} {b} {action.wait} {action.repetitions}'
            elif isinstance(action, RgbRingProgressWheelStepAction):
                command = f'progress_wheel_step {r} {g} {b}'
            elif isinstance(action, RgbRingPulseAction):
                command = f'pulse {r} {g} {b} {action.wait} {action.repetitions}'
            elif isinstance(action, RgbRingSpinningWheelAction):
                command = f"""spinning_wheel {r} {g} {b} {action.wait} {action.length} {
                action.repetitions}"""
            elif isinstance(action, RgbRingProgressWheelAction):
                command = f'progress_wheel {r} {g} {b} {action.percentage}'
            elif isinstance(action, RgbRingFillUptoAction):
                command = f'fill_upto {r} {g} {b} {action.percentage} {action.wait}'
            elif isinstance(action, RgbRingFillDownfromAction):
                command = f'fill_downfrom {r} {g} {b} {action.percentage} {action.wait}'
        elif isinstance(action, RgbRingSetEnabledAction):
            command = 'set_enabled ' + str(int(action.enabled))
        elif isinstance(action, RgbRingSetBrightnessAction):
            if 0 <= action.brightness <= 1:
                command = f'set_brightness {action.brightness}'
        elif isinstance(action, RgbRingBlankAction):
            command = 'blank'
        elif isinstance(action, RgbRingRainbowAction):
            command = f'rainbow {action.rounds} {action.wait}'

        if not command:
            return state

        return CompleteReducerResult(
            state=state,
            events=[RgbRingCommandEvent(command=command.split())],
        )

    return state
