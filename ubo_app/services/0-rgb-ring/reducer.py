# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.led_ring import (
    LedRingAction,
    LedRingBlankAction,
    LedRingBlinkAction,
    LedRingColorfulCommandAction,
    LedRingCommandAction,
    LedRingCommandEvent,
    LedRingFillDownfromAction,
    LedRingFillUptoAction,
    LedRingProgressWheelAction,
    LedRingProgressWheelStepAction,
    LedRingPulseAction,
    LedRingRainbowAction,
    LedRingSetAllAction,
    LedRingSetBrightnessAction,
    LedRingSetEnabledAction,
    LedRingSetIsBusyAction,
    LedRingSetIsConnectedAction,
    LedRingSpinningWheelAction,
    LedRingState,
)

Action = InitAction | LedRingAction


def reducer(  # noqa: C901, PLR0912
    state: LedRingState | None,
    action: Action,
) -> ReducerResult[LedRingState, Action, LedRingCommandEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return LedRingState(is_connected=False, is_busy=False)
        raise InitializationActionError(action)

    if isinstance(action, LedRingSetIsConnectedAction):
        return replace(
            state,
            is_connected=action.is_connected,
        )

    if isinstance(action, LedRingSetIsBusyAction):
        return replace(
            state,
            is_busy=action.is_busy,
        )

    if isinstance(action, LedRingCommandAction):
        if not state.is_connected:
            return state

        command = None

        if isinstance(action, LedRingColorfulCommandAction):
            (r, g, b, *_) = action.color
            if isinstance(action, LedRingSetAllAction):
                command = f'set_all {r} {g} {b}'
            elif isinstance(action, LedRingBlinkAction):
                command = f'blink {r} {g} {b} {action.wait} {action.repetitions}'
            elif isinstance(action, LedRingProgressWheelStepAction):
                command = f'progress_wheel_step {r} {g} {b}'
            elif isinstance(action, LedRingPulseAction):
                command = f'pulse {r} {g} {b} {action.wait} {action.repetitions}'
            elif isinstance(action, LedRingSpinningWheelAction):
                command = f"""spinning_wheel {r} {g} {b} {action.wait} {action.length} {
                action.repetitions}"""
            elif isinstance(action, LedRingProgressWheelAction):
                command = f'progress_wheel {r} {g} {b} {action.percentage}'
            elif isinstance(action, LedRingFillUptoAction):
                command = f'fill_upto {r} {g} {b} {action.percentage} {action.wait}'
            elif isinstance(action, LedRingFillDownfromAction):
                command = f'fill_downfrom {r} {g} {b} {action.percentage} {action.wait}'
        elif isinstance(action, LedRingSetEnabledAction):
            command = 'set_enabled ' + str(int(action.enabled))
        elif isinstance(action, LedRingSetBrightnessAction):
            if 0 <= action.brightness <= 1:
                command = f'set_brightness {action.brightness}'
        elif isinstance(action, LedRingBlankAction):
            command = 'blank'
        elif isinstance(action, LedRingRainbowAction):
            command = f'rainbow {action.rounds} {action.wait}'

        if not command:
            return state

        return CompleteReducerResult(
            state=state,
            events=[LedRingCommandEvent(command=command)],
        )

    return state
