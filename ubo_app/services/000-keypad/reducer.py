"""Keypad reducer."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

from redux import (
    CompleteReducerResult,
    FinishEvent,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.core.types import (
    MainEvent,
    MenuChooseByIndexEvent,
    MenuEvent,
    MenuGoBackEvent,
    MenuGoHomeEvent,
    MenuScrollDirection,
    MenuScrollEvent,
    ReplayRecordedSequenceAction,
    ScreenshotEvent,
    SetMenuPathAction,
    SnapshotEvent,
    ToggleRecordingAction,
)
from ubo_app.store.services.audio import AudioChangeVolumeAction, AudioDevice
from ubo_app.store.services.keypad import (
    Key,
    KeypadAction,
    KeypadKeyPressAction,
    KeypadKeyReleaseAction,
    KeypadState,
)
from ubo_app.store.services.notifications import Notification, NotificationsAddAction

if TYPE_CHECKING:
    from ubo_app.store.services.audio import AudioAction

Action = KeypadAction | SetMenuPathAction | InitAction


def reducer(
    state: KeypadState | None,
    action: Action,
) -> (
    ReducerResult[
        KeypadState,
        AudioAction
        | NotificationsAddAction
        | ToggleRecordingAction
        | ReplayRecordedSequenceAction,
        FinishEvent | MenuEvent | MainEvent,
    ]
    | None
):
    """Keypad reducer."""
    if state is None:
        if isinstance(action, InitAction):
            return KeypadState()

        raise InitializationActionError(action)

    match action:
        case KeypadKeyPressAction(key=Key.UP) if (
            state.depth == 1 and action.pressed_keys == {action.key}
        ):
            return CompleteReducerResult(
                state=state,
                actions=[
                    AudioChangeVolumeAction(
                        amount=0.05,
                        device=AudioDevice.OUTPUT,
                    ),
                ],
            )
        case KeypadKeyPressAction(key=Key.DOWN) if (
            state.depth == 1 and action.pressed_keys == {action.key}
        ):
            return CompleteReducerResult(
                state=state,
                actions=[
                    AudioChangeVolumeAction(
                        amount=-0.05,
                        device=AudioDevice.OUTPUT,
                    ),
                ],
            )
        case KeypadKeyPressAction(key=Key.L1) if action.pressed_keys == {action.key}:
            return CompleteReducerResult(
                state=state,
                events=[MenuChooseByIndexEvent(index=0)],
            )
        case KeypadKeyPressAction(key=Key.L2) if action.pressed_keys == {action.key}:
            return CompleteReducerResult(
                state=state,
                events=[MenuChooseByIndexEvent(index=1)],
            )
        case KeypadKeyPressAction(key=Key.L3) if action.pressed_keys == {action.key}:
            return CompleteReducerResult(
                state=state,
                events=[MenuChooseByIndexEvent(index=2)],
            )
        case KeypadKeyPressAction(key=Key.UP) if action.pressed_keys == {action.key}:
            return CompleteReducerResult(
                state=state,
                events=[MenuScrollEvent(direction=MenuScrollDirection.UP)],
            )
        case KeypadKeyPressAction(key=Key.DOWN) if action.pressed_keys == {action.key}:
            return CompleteReducerResult(
                state=state,
                events=[MenuScrollEvent(direction=MenuScrollDirection.DOWN)],
            )
        case KeypadKeyPressAction(key=Key.L1) if action.pressed_keys == {
            Key.HOME,
            Key.L1,
        }:
            return CompleteReducerResult(
                state=state,
                events=[ScreenshotEvent()],
            )
        case KeypadKeyPressAction(key=Key.L2) if action.pressed_keys == {
            Key.HOME,
            Key.L2,
        }:
            return CompleteReducerResult(
                state=state,
                events=[SnapshotEvent()],
            )
        case KeypadKeyPressAction(key=Key.L3) if action.pressed_keys == {
            Key.HOME,
            Key.L3,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[ToggleRecordingAction()],
            )
        case KeypadKeyPressAction(key=Key.L3) if action.pressed_keys == {
            Key.BACK,
            Key.L3,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[ReplayRecordedSequenceAction()],
            )
        case KeypadKeyPressAction(key=Key.BACK) if action.pressed_keys == {
            Key.HOME,
            Key.BACK,
        }:
            return CompleteReducerResult(
                state=state,
                events=[FinishEvent()],
            )
        # DEMO {
        case KeypadKeyPressAction(key=Key.UP) if action.pressed_keys == {
            Key.HOME,
            Key.UP,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[
                    NotificationsAddAction(
                        notification=Notification(
                            title='Test notification with progress',
                            content='This is a test notification with progress',
                            progress=0.5,
                        ),
                    ),
                ],
            )
        case KeypadKeyPressAction(key=Key.DOWN) if action.pressed_keys == {
            Key.HOME,
            Key.DOWN,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[
                    NotificationsAddAction(
                        notification=Notification(
                            icon='',
                            title='Test notification with spinner',
                            content='This is a test notification with spinner',
                            progress=math.nan,
                        ),
                    ),
                ],
            )
        # DEMO }
        case KeypadKeyPressAction():
            return state

        case KeypadKeyReleaseAction(pressed_keys=set(), key=Key.BACK):
            return CompleteReducerResult(
                state=state,
                events=[MenuGoBackEvent()],
            )
        case KeypadKeyReleaseAction(pressed_keys=set(), key=Key.HOME):
            return CompleteReducerResult(
                state=state,
                events=[MenuGoHomeEvent()],
            )
        case KeypadKeyReleaseAction():
            return state

        case SetMenuPathAction():
            return replace(state, depth=action.depth)

        case _:
            return state
