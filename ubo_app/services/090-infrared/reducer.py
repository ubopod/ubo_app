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
    AssistantToggleListeningAction,
)
from ubo_app.store.services.infrared import (
    InfraredAction,
    InfraredAddDeviceAction,
    InfraredDevice,
    InfraredDeviceRegistrationCompleteEvent,
    InfraredDeviceRegistrationStartedEvent,
    InfraredHandleReceivedCodeAction,
    InfraredRegisterDeviceAction,
    InfraredRemoveDeviceAction,
    InfraredSendCodeAction,
    InfraredSendCodeEvent,
    InfraredSetIsRegisteringDeviceAction,
    InfraredSetRegistrationCodeAction,
    InfraredSetShouldPropagateAction,
    InfraredSetShouldReceiveAction,
    InfraredState,
)
from ubo_app.store.services.rgb_ring import RgbRingBlankAction, RgbRingBlinkAction
from ubo_app.store.services.keypad import (
    Key,
    KeypadAction,
    KeypadKeyPressAction,
    KeypadKeyReleaseAction,
)

KeyActionType = type[KeypadKeyPressAction] | type[KeypadKeyReleaseAction]

KEY_TO_INFRARED_CODES: dict[KeyActionType, dict[Key, tuple[str, str]]] = {
    KeypadKeyPressAction: {
        Key.L1: ('necx', '0xbf10'),
        Key.L2: ('necx', '0xbf11'),
        Key.L3: ('necx', '0xbf12'),
        Key.UP: ('nex', '0xbf05'),
        Key.DOWN: ('necx', '0xbf0d'),
        Key.BACK: ('necx', '0x1a'),
        Key.HOME: ('necx', '0x1c'),
    },
    KeypadKeyReleaseAction: {
        Key.L1: ('necx', '0x7076d'),
        Key.L2: ('necx', '0x70716'),
        Key.L3: ('necx', '0x70716'),
        Key.UP: ('necx', '0xbf06'),
        Key.DOWN: ('necx', '0x00feb05f'),
        Key.BACK: ('necx', '0xbf0e'),
        Key.HOME: ('necx', '0xbf09'),
    },
}
INFRARED_CODES_TO_KEY: dict[tuple[str, str], tuple[KeyActionType, Key]] = {
    (protocol, scancode): (action_type, key)
    for action_type in KEY_TO_INFRARED_CODES
    for key, (protocol, scancode) in KEY_TO_INFRARED_CODES[action_type].items()
}

# Define mappings for IR codes that should trigger Assistant actions
ASSISTANT_IR_CODES = {
    ('necx', '0xbf04'): AssistantStartListeningAction,
    ('necx', '0xbf06'): AssistantStopListeningAction,
    ('nec', '0xa01b'): AssistantToggleListeningAction,
}


def reducer(
    state: InfraredState | None,
    action: InfraredAction | KeypadAction,
) -> ReducerResult[
    InfraredState,
    InfraredAction | KeypadKeyPressAction | KeypadKeyReleaseAction | RgbRingBlinkAction | RgbRingBlankAction,
    InfraredSendCodeEvent | InfraredDeviceRegistrationStartedEvent | InfraredDeviceRegistrationCompleteEvent,
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

        case InfraredRegisterDeviceAction():
            actions = [
                RgbRingBlinkAction(
                    color=(0, 255, 0),
                    repetitions=1000,  # Large number to keep blinking until stopped
                    wait=400,
                ),
            ]
            # Only enable receiving if it's not already enabled to avoid async conflicts
            if not state.should_receive_keypad_actions:
                actions.append(InfraredSetShouldReceiveAction(should_receive=True))
            return CompleteReducerResult(
                state=replace(
                    state,
                    is_registering_device=True,
                    registration_signal_counts={},
                ),
                actions=actions,
                events=[InfraredDeviceRegistrationStartedEvent()],
            )

        case InfraredSetIsRegisteringDeviceAction():
            return replace(
                state,
                is_registering_device=action.is_registering,
            )

        case InfraredAddDeviceAction():
            # Check if device already exists
            device_key = (action.protocol, action.scancode)
            existing_device = next(
                (
                    device
                    for device in state.registered_devices
                    if (device.protocol, device.scancode) == device_key
                ),
                None,
            )
            if existing_device:
                # Update existing device name
                new_devices = [
                    InfraredDevice(
                        name=action.name,
                        protocol=action.protocol,
                        scancode=action.scancode,
                    )
                    if (device.protocol, device.scancode) == device_key
                    else device
                    for device in state.registered_devices
                ]
            else:
                # Add new device
                new_devices = [
                    *state.registered_devices,
                    InfraredDevice(
                        name=action.name,
                        protocol=action.protocol,
                        scancode=action.scancode,
                    ),
                ]
            return replace(
                state,
                registered_devices=new_devices,
            )

        case InfraredRemoveDeviceAction():
            device_key = (action.protocol, action.scancode)
            new_devices = [
                device
                for device in state.registered_devices
                if (device.protocol, device.scancode) != device_key
            ]
            return replace(
                state,
                registered_devices=new_devices,
            )

        case InfraredHandleReceivedCodeAction() if state.is_registering_device:
            ir_code = (action.protocol, action.scancode)
            # Get current count for this signal, or 0 if it's new
            current_count = state.registration_signal_counts.get(ir_code, 0)
            new_count = current_count + 1
            
            # Update the count for this signal
            new_counts = {**state.registration_signal_counts, ir_code: new_count}
            
            logger.info(
                'Device registration: Signal received',
                extra={
                    'protocol': action.protocol,
                    'scancode': action.scancode,
                    'repetition_count': new_count,
                },
            )
            
            # Check if this signal has reached 5 repetitions
            if new_count >= 5:
                logger.info(
                    'Device registration: Signal repeated 5 times - registration complete',
                    extra={
                        'protocol': action.protocol,
                        'scancode': action.scancode,
                        'repetition_count': new_count,
                    },
                )
                logger.info(
                    'Device registration: Emitting InfraredDeviceRegistrationCompleteEvent',
                    extra={
                        'protocol': action.protocol,
                        'scancode': action.scancode,
                    },
                )
                return CompleteReducerResult(
                    state=replace(
                        state,
                        is_registering_device=False,
                        registration_signal_counts={},
                    ),
                    actions=[
                        RgbRingBlankAction(),  # Stop blinking
                        InfraredSetShouldReceiveAction(should_receive=False),  # Turn off IR receiving
                    ],
                    events=[
                        InfraredDeviceRegistrationCompleteEvent(
                            protocol=action.protocol,
                            scancode=action.scancode,
                        ),
                    ],
                )
            
            # Update state with new counts
            return replace(
                state,
                registration_signal_counts=new_counts,
            )

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
