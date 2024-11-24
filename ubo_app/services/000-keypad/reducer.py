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


def reducer(
    state: KeypadState | None,
    action: KeypadAction,
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

    if isinstance(action, KeypadKeyPressAction):
        if action.pressed_keys == {action.key}:
            if action.key == Key.UP and state.depth == 1:
                return CompleteReducerResult(
                    state=state,
                    actions=[
                        AudioChangeVolumeAction(
                            amount=0.05,
                            device=AudioDevice.OUTPUT,
                        ),
                    ],
                )
            if action.key == Key.DOWN and state.depth == 1:
                return CompleteReducerResult(
                    state=state,
                    actions=[
                        AudioChangeVolumeAction(
                            amount=-0.05,
                            device=AudioDevice.OUTPUT,
                        ),
                    ],
                )

            if action.key == Key.L1:
                return CompleteReducerResult(
                    state=state,
                    events=[MenuChooseByIndexEvent(index=0)],
                )
            if action.key == Key.L2:
                return CompleteReducerResult(
                    state=state,
                    events=[MenuChooseByIndexEvent(index=1)],
                )
            if action.key == Key.L3:
                return CompleteReducerResult(
                    state=state,
                    events=[MenuChooseByIndexEvent(index=2)],
                )
            if action.key == Key.UP:
                return CompleteReducerResult(
                    state=state,
                    events=[MenuScrollEvent(direction=MenuScrollDirection.UP)],
                )
            if action.key == Key.DOWN:
                return CompleteReducerResult(
                    state=state,
                    events=[MenuScrollEvent(direction=MenuScrollDirection.DOWN)],
                )
        else:
            if action.pressed_keys == {Key.HOME, Key.L1} and action.key == Key.L1:
                return CompleteReducerResult(
                    state=state,
                    events=[ScreenshotEvent()],
                )
            if action.pressed_keys == {Key.HOME, Key.L2} and action.key == Key.L2:
                return CompleteReducerResult(
                    state=state,
                    events=[SnapshotEvent()],
                )
            if action.pressed_keys == {Key.HOME, Key.L3} and action.key == Key.L3:
                return CompleteReducerResult(
                    state=state,
                    actions=[ToggleRecordingAction()],
                )
            if action.pressed_keys == {Key.BACK, Key.L3} and action.key == Key.L3:
                return CompleteReducerResult(
                    state=state,
                    actions=[ReplayRecordedSequenceAction()],
                )
            if action.pressed_keys == {Key.HOME, Key.BACK} and action.key == Key.BACK:
                return CompleteReducerResult(
                    state=state,
                    events=[FinishEvent()],
                )

            # DEMO {
            if action.pressed_keys == {Key.HOME, Key.UP} and action.key == Key.UP:
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
            if action.pressed_keys == {Key.HOME, Key.DOWN} and action.key == Key.DOWN:
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
        return state

    if isinstance(action, KeypadKeyReleaseAction):
        if len(action.pressed_keys) == 0:
            if action.key == Key.BACK:
                return CompleteReducerResult(
                    state=state,
                    events=[MenuGoBackEvent()],
                )
            if action.key == Key.HOME:
                return CompleteReducerResult(
                    state=state,
                    events=[MenuGoHomeEvent()],
                )

        return state

    if isinstance(action, SetMenuPathAction):
        return replace(state, depth=action.depth)

    return state
