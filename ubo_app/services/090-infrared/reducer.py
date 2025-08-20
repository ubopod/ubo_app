"""Reducer for infrared actions."""

from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.logger import logger
from ubo_app.store.services.assistant import (
    AssistantStartListeningAction,
    AssistantStopListeningAction,
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

KEY_TO_INFRARED_CODES: dict[KeyActionType, dict[Key, tuple[str, str]]] = {
    KeypadKeyPressAction: {
        Key.L1: ('necx', '0x7076c'),
        Key.L2: ('necx', '0x70714'),
        Key.L3: ('necx', '0x70715'),
        Key.UP: ('necx', '0x70760'),
        Key.DOWN: ('necx', '0x70761'),
        Key.BACK: ('necx', '0x70757'),
        Key.HOME: ('necx', '0x70778'),
    },
    KeypadKeyReleaseAction: {
        Key.L1: ('necx', '0x7076d'),
        Key.L2: ('necx', '0x70716'),
        Key.L3: ('necx', '0x70716'),
        Key.UP: ('necx', '0xbf06'),
        Key.DOWN: ('necx', '0x00feb05f'),
        Key.BACK: ('necx', '0x70758'),
        Key.HOME: ('necx', '0x70779'),
    },
}
INFRARED_CODES_TO_KEY: dict[tuple[str, str], tuple[KeyActionType, Key]] = {
    (protocol, scancode): (action_type, key)
    for action_type in KEY_TO_INFRARED_CODES
    for key, (protocol, scancode) in KEY_TO_INFRARED_CODES[action_type].items()
}

# Define mappings for IR codes that should trigger Assistant actions
ASSISTANT_IR_CODES = {
    ('necx', '0x70749'): AssistantStartListeningAction,
    ('necx', '0x70746'): AssistantStopListeningAction,
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

    match action:
        case InfraredSendCodeAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    InfraredSendCodeEvent(
                        protocol=action.protocol,
                        scancode=action.scancode,
                    ),
                ],
            )

        case InfraredSetShouldPropagateAction():
            return replace(
                state,
                should_propagate_keypad_actions=action.should_propagate,
            )

        case InfraredSetShouldReceiveAction():
            return replace(state, should_receive_keypad_actions=action.should_receive)

        case KeypadKeyPressAction() | KeypadKeyReleaseAction() if (
            state.should_propagate_keypad_actions
        ):
            return CompleteReducerResult(
                state=state,
                actions=[
                    InfraredSendCodeAction(
                        protocol=KEY_TO_INFRARED_CODES[type(action)][action.key][0],
                        scancode=KEY_TO_INFRARED_CODES[type(action)][action.key][1],
                    ),
                ],
            )

        case InfraredHandleReceivedCodeAction() if state.should_receive_keypad_actions:
            logger.info(
                'Received infrared code: %s, %s',
                action.protocol,
                action.scancode,
            )
            ir_code = (action.protocol, action.scancode)
            if ir_code in ASSISTANT_IR_CODES:
                action_class = ASSISTANT_IR_CODES[ir_code]
                logger.info(
                    'Triggered Assistant action: %s',
                    action_class,
                )
                return CompleteReducerResult(
                    state=state,
                    actions=[
                        action_class(),
                    ],
                )
            if ir_code not in INFRARED_CODES_TO_KEY:
                return state

            key_action_type, key = INFRARED_CODES_TO_KEY[
                (action.protocol, action.scancode)
            ]

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

        case _:
            return state
