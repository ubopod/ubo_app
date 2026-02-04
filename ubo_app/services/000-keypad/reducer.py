"""Keypad reducer."""

from __future__ import annotations

import math
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
    MenuStackItem,
    ReplayRecordedSequenceAction,
    ScreenshotEvent,
    SnapshotEvent,
    ToggleRecordingAction,
)
from ubo_app.store.services.assistant import (
    AssistantAction,
    AssistantStartListeningAction,
    AssistantStopListeningAction,
)
from ubo_app.store.services.audio import (
    AudioChangeVolumeAction,
    AudioDevice,
    AudioPlayRecordingAction,
    AudioToggleRecordingAction,
)
from ubo_app.store.services.display import (
    DisplayUnblankAction,
    DisplayUpdateActivityAction,
)
from ubo_app.store.services.keypad import (
    Key,
    KeypadAction,
    KeypadKeyHoldAction,
    KeypadKeyPressAction,
    KeypadKeyReleaseAction,
    KeypadKeyUnholdAction,
    KeypadState,
)
from ubo_app.store.services.notifications import Notification, NotificationsAddAction

if TYPE_CHECKING:
    from ubo_app.store.core.types import StackItemType
    from ubo_app.store.services.audio import AudioAction

Action = KeypadAction | InitAction


def _compute_depth_from_stack(stack: tuple[StackItemType, ...]) -> int:
    """Compute menu depth from the navigation stack.

    Depth is the count of MenuStackItems in the stack.
    """
    return len([item for item in stack if isinstance(item, MenuStackItem)])


def reducer(
    state: KeypadState | None,
    action: Action,
) -> (
    ReducerResult[
        KeypadState,
        AudioAction
        | NotificationsAddAction
        | ToggleRecordingAction
        | ReplayRecordedSequenceAction
        | AssistantAction
        | DisplayUnblankAction
        | DisplayUpdateActivityAction,
        FinishEvent | MenuEvent | MainEvent,
    ]
    | None
):
    """Keypad reducer."""
    if state is None:
        if isinstance(action, InitAction):
            return KeypadState()

        raise InitializationActionError(action)

    # Query current depth from the main state stack
    from ubo_app.store.main import store

    @store.with_state(lambda s: s.main.stack)
    def get_current_depth(stack: tuple[StackItemType, ...]) -> int:
        return _compute_depth_from_stack(stack)

    depth = get_current_depth()

    # Check if this key press should wake up a blanked screen
    if isinstance(action, KeypadKeyPressAction) and not state.is_consumed:

        @store.with_state(
            lambda s: s.display.is_blanked if hasattr(s, 'display') else False,
        )
        def is_display_blanked(is_blanked: bool) -> bool:  # noqa: FBT001
            return is_blanked

        if is_display_blanked():
            # Screen is blanked, wake it up and consume this key press
            return CompleteReducerResult(
                state=state(is_consumed=True),
                actions=[DisplayUnblankAction()],
            )

    match action:
        case KeypadKeyPressAction(key=Key.UP) if (
            depth == 1 and action.pressed_keys == {action.key}
        ):
            return CompleteReducerResult(
                state=state,
                actions=[
                    DisplayUpdateActivityAction(),
                    AudioChangeVolumeAction(
                        amount=0.05,
                        device=AudioDevice.OUTPUT,
                    ),
                ],
            )
        case KeypadKeyPressAction(key=Key.DOWN) if (
            depth == 1 and action.pressed_keys == {action.key}
        ):
            return CompleteReducerResult(
                state=state,
                actions=[
                    DisplayUpdateActivityAction(),
                    AudioChangeVolumeAction(
                        amount=-0.05,
                        device=AudioDevice.OUTPUT,
                    ),
                ],
            )
        case KeypadKeyPressAction(key=Key.HOME) if (
            depth == 1 and action.pressed_keys == {action.key}
        ):
            return CompleteReducerResult(
                state=state,
                actions=[
                    DisplayUpdateActivityAction(),
                    AssistantStartListeningAction(),
                ],
            )
        case KeypadKeyReleaseAction(pressed_keys=set(), key=Key.HOME) if (
            depth == 1
        ):
            return CompleteReducerResult(
                state=state,
                actions=[
                    AssistantStopListeningAction(),
                ],
            )
        case KeypadKeyPressAction(key=Key.L1) if action.pressed_keys == {action.key}:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[MenuChooseByIndexEvent(index=0)],
            )
        case KeypadKeyPressAction(key=Key.L2) if action.pressed_keys == {action.key}:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[MenuChooseByIndexEvent(index=1)],
            )
        case KeypadKeyPressAction(key=Key.L3) if action.pressed_keys == {action.key}:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[MenuChooseByIndexEvent(index=2)],
            )
        case KeypadKeyPressAction(key=Key.UP) if action.pressed_keys == {action.key}:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[MenuScrollEvent(direction=MenuScrollDirection.UP)],
            )
        case KeypadKeyPressAction(key=Key.DOWN) if action.pressed_keys == {action.key}:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[MenuScrollEvent(direction=MenuScrollDirection.DOWN)],
            )
        case KeypadKeyPressAction(key=Key.L1) if action.pressed_keys == {
            Key.HOME,
            Key.L1,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[ScreenshotEvent()],
            )
        case KeypadKeyPressAction(key=Key.L2) if action.pressed_keys == {
            Key.HOME,
            Key.L2,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[SnapshotEvent()],
            )
        case KeypadKeyPressAction(key=Key.L3) if action.pressed_keys == {
            Key.HOME,
            Key.L3,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction(), ToggleRecordingAction()],
            )
        case KeypadKeyPressAction(key=Key.L1) if action.pressed_keys == {
            Key.BACK,
            Key.L1,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction(), AudioToggleRecordingAction()],
            )
        case KeypadKeyPressAction(key=Key.L2) if action.pressed_keys == {
            Key.BACK,
            Key.L2,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction(), AudioPlayRecordingAction()],
            )
        case KeypadKeyPressAction(key=Key.L3) if action.pressed_keys == {
            Key.BACK,
            Key.L3,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction(), ReplayRecordedSequenceAction()],
            )
        case KeypadKeyPressAction(key=Key.BACK) if action.pressed_keys == {
            Key.HOME,
            Key.BACK,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
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
                    DisplayUpdateActivityAction(),
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
                    DisplayUpdateActivityAction(),
                    NotificationsAddAction(
                        notification=Notification(
                            icon='',
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

        case KeypadKeyHoldAction(key=Key.HOME) if (
            action.pressed_keys
            == {
                Key.HOME,
            }
            and action.held_keys == {Key.HOME}
            and depth > 1
        ):
            return CompleteReducerResult(
                state=state(is_consumed=True),
                actions=[AssistantStartListeningAction()],
            )

        case KeypadKeyUnholdAction(key=Key.HOME):
            return CompleteReducerResult(
                state=state(is_consumed=True),
                actions=[AssistantStopListeningAction()],
            )

        case KeypadKeyReleaseAction() if state.is_consumed:
            return state(is_consumed=False)

        case KeypadKeyReleaseAction(pressed_keys=set(), key=Key.BACK):
            return CompleteReducerResult(
                state=state,
                events=[MenuGoBackEvent()],
            )
        case KeypadKeyReleaseAction(pressed_keys=set(), key=Key.HOME):
            return CompleteReducerResult(
                state=state,
                actions=[AssistantStopListeningAction()],
                events=[MenuGoHomeEvent()],
            )

        case _:
            return state
