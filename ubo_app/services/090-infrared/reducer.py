"""Reducer for infrared actions."""

from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.infrared import (
    InfraredAction,
    InfraredHandleReceivedCodeAction,
    InfraredSendCodeAction,
    InfraredSendCodeEvent,
    InfraredSetShouldPropagateAction,
    InfraredSetShouldReceiveAction,
    InfraredState,
)
from ubo_app.store.services.keypad import (
    Key,
    KeypadAction,
    KeypadKeyPressAction,
    KeypadKeyReleaseAction,
)

KeyActionType = type[KeypadKeyPressAction] | type[KeypadKeyReleaseAction]

KEY_TO_INFRARED_CODES: dict[KeyActionType, dict[Key, tuple[int, ...]]] = {
    KeypadKeyPressAction: {
        Key.L1: (0x00, 0xFD, 0x08, 0xF7),
        Key.L2: (0x00, 0xFD, 0x88, 0x77),
        Key.L3: (0x00, 0xFD, 0x08, 0xB7),
        Key.UP: (0x00, 0xFD, 0xA0, 0x5F),
        Key.DOWN: (0x00, 0xFD, 0xB0, 0x5F),
        Key.BACK: (0x00, 0xFE, 0x30, 0x9F),
        Key.HOME: (0x00, 0xFE, 0x60, 0x9F),
    },
    KeypadKeyReleaseAction: {
        Key.L1: (0x00, 0xFE, 0x08, 0xF7),
        Key.L2: (0x00, 0xFE, 0x88, 0x77),
        Key.L3: (0x00, 0xFE, 0x08, 0xB7),
        Key.UP: (0x00, 0xFE, 0xA0, 0x5F),
        Key.DOWN: (0x00, 0xFE, 0xB0, 0x5F),
        Key.BACK: (0x00, 0xFD, 0x30, 0x9F),
        Key.HOME: (0x00, 0xFD, 0x60, 0x9F),
    },
}
INFRARED_CODES_TO_KEY: dict[tuple[int, ...], tuple[KeyActionType, Key]] = {
    code: (action_type, key)
    for action_type in KEY_TO_INFRARED_CODES
    for key, code in KEY_TO_INFRARED_CODES[action_type].items()
}


def reducer(
    state: InfraredState | None,
    action: InfraredAction | KeypadAction,
) -> ReducerResult[
    InfraredState,
    InfraredAction | KeypadKeyPressAction | KeypadKeyReleaseAction,
    InfraredSendCodeEvent,
]:
    """Reducer for infrared actions."""
    if state is None:
        if isinstance(action, InitAction):
            return InfraredState()

        raise InitializationActionError(action)

    if isinstance(action, InfraredSendCodeAction):
        return CompleteReducerResult(
            state=state,
            events=[InfraredSendCodeEvent(code=action.code)],
        )

    if isinstance(action, InfraredSetShouldPropagateAction):
        return replace(state, should_propagate_keypad_actions=action.should_propagate)

    if isinstance(action, InfraredSetShouldReceiveAction):
        return replace(state, should_receive_keypad_actions=action.should_receive)

    if (
        isinstance(action, (KeypadKeyPressAction, KeypadKeyReleaseAction))
        and state.should_propagate_keypad_actions
    ):
        return CompleteReducerResult(
            state=state,
            actions=[
                InfraredSendCodeAction(
                    code=KEY_TO_INFRARED_CODES[type(action)][action.key],
                ),
            ],
        )

    if (
        isinstance(action, InfraredHandleReceivedCodeAction)
        and state.should_receive_keypad_actions
    ):
        if action.code not in INFRARED_CODES_TO_KEY:
            return state

        key_action_type, key = INFRARED_CODES_TO_KEY[action.code]

        if key_action_type is KeypadKeyPressAction:
            return CompleteReducerResult(
                state=state,
                actions=[
                    KeypadKeyPressAction(key=key, pressed_keys={key}),
                ],
            )
        if key_action_type is KeypadKeyReleaseAction:
            return CompleteReducerResult(
                state=state,
                actions=[
                    KeypadKeyReleaseAction(key=key, pressed_keys=set()),
                ],
            )

    return state
