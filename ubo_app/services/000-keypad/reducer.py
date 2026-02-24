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

from ubo_app.logger import logger
from ubo_app.store.core.types import (
    MainEvent,
    MenuChooseByIndexEvent,
    MenuEvent,
    MenuGoBackEvent,
    MenuGoHomeEvent,
    MenuScrollDirection,
    MenuScrollEvent,
    MenuStackItem,
    NotificationStackItem,
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


def _is_on_notification(stack: tuple[StackItemType, ...]) -> bool:
    """Check if the top of the stack is a notification view."""
    return bool(stack) and isinstance(stack[-1], NotificationStackItem)


def _notification_has_item_at(
    stack: tuple[StackItemType, ...],
    index: int,
) -> bool:
    """Check if the notification at the top of the stack has an item at the given index.

    Uses the same padding logic as the notification handler: items are
    right-aligned to PAGE_SIZE (3), so index 0 = top, 2 = bottom.
    """
    from ubo_app.store.core.constants import PAGE_SIZE

    if not stack or not isinstance(stack[-1], NotificationStackItem):
        return False

    from ubo_app.store.main import RootState, store

    @store.with_state(lambda s: s)
    def _check(state: RootState) -> bool:
        from ubo_app.store.core.view_computation import get_notification_view_data

        notification_item = stack[-1]
        if not isinstance(notification_item, NotificationStackItem):
            return False
        view_data = get_notification_view_data(
            state,
            notification_item.notification_id,
        )
        items = view_data.items
        if not items:
            return False
        real_items = [item for item in items if item is not None]
        pad = PAGE_SIZE - len(real_items)
        real_index = index - pad
        return 0 <= real_index < len(real_items)

    return _check()


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

    # Query current stack from the main state
    from ubo_app.store.main import store

    @store.with_state(lambda s: s.main.stack)
    def get_stack(stack: tuple[StackItemType, ...]) -> tuple[StackItemType, ...]:
        return stack

    stack = get_stack()
    depth = _compute_depth_from_stack(stack)
    on_notification = _is_on_notification(stack)

    if isinstance(action, KeypadKeyPressAction):
        top = stack[-1] if stack else None
        logger.info(
            '[Keypad] key_press: key=%s, pressed_keys=%s, depth=%d, '
            'on_notification=%s, top=%s',
            action.key,
            action.pressed_keys,
            depth,
            on_notification,
            type(top).__name__ if top else 'None',
        )

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
            depth == 1
            and not on_notification
            and set(action.pressed_keys) == {action.key}
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
            depth == 1
            and not on_notification
            and set(action.pressed_keys) == {action.key}
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
            depth == 1 and set(action.pressed_keys) == {action.key}
        ):
            return CompleteReducerResult(
                state=state,
                actions=[
                    DisplayUpdateActivityAction(),
                    AssistantStartListeningAction(),
                ],
            )
        case KeypadKeyReleaseAction(pressed_keys=(), key=Key.HOME) if (
            depth == 1
        ):
            return CompleteReducerResult(
                state=state,
                actions=[
                    AssistantStopListeningAction(),
                ],
            )
        case KeypadKeyPressAction(key=Key.L1) if (
            set(action.pressed_keys) == {action.key}
        ):
            if on_notification and not _notification_has_item_at(stack, 0):
                return CompleteReducerResult(
                    state=state,
                    actions=[DisplayUpdateActivityAction()],
                )
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[MenuChooseByIndexEvent(index=0)],
            )
        case KeypadKeyPressAction(key=Key.L2) if (
            set(action.pressed_keys) == {action.key}
        ):
            if on_notification and not _notification_has_item_at(stack, 1):
                return CompleteReducerResult(
                    state=state,
                    actions=[DisplayUpdateActivityAction()],
                )
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[MenuChooseByIndexEvent(index=1)],
            )
        case KeypadKeyPressAction(key=Key.L3) if (
            set(action.pressed_keys) == {action.key}
        ):
            if on_notification and not _notification_has_item_at(stack, 2):
                return CompleteReducerResult(
                    state=state,
                    actions=[DisplayUpdateActivityAction()],
                )
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[MenuChooseByIndexEvent(index=2)],
            )
        case KeypadKeyPressAction(key=Key.UP) if (
            set(action.pressed_keys) == {action.key}
        ):
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[MenuScrollEvent(direction=MenuScrollDirection.UP)],
            )
        case KeypadKeyPressAction(key=Key.DOWN) if (
            set(action.pressed_keys) == {action.key}
        ):
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[MenuScrollEvent(direction=MenuScrollDirection.DOWN)],
            )
        case KeypadKeyPressAction(key=Key.L1) if set(action.pressed_keys) == {
            Key.HOME,
            Key.L1,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[ScreenshotEvent()],
            )
        case KeypadKeyPressAction(key=Key.L2) if set(action.pressed_keys) == {
            Key.HOME,
            Key.L2,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[SnapshotEvent()],
            )
        case KeypadKeyPressAction(key=Key.L3) if set(action.pressed_keys) == {
            Key.HOME,
            Key.L3,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction(), ToggleRecordingAction()],
            )
        case KeypadKeyPressAction(key=Key.L1) if set(action.pressed_keys) == {
            Key.BACK,
            Key.L1,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction(), AudioToggleRecordingAction()],
            )
        case KeypadKeyPressAction(key=Key.L2) if set(action.pressed_keys) == {
            Key.BACK,
            Key.L2,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction(), AudioPlayRecordingAction()],
            )
        case KeypadKeyPressAction(key=Key.L3) if set(action.pressed_keys) == {
            Key.BACK,
            Key.L3,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction(), ReplayRecordedSequenceAction()],
            )
        case KeypadKeyPressAction(key=Key.BACK) if set(action.pressed_keys) == {
            Key.HOME,
            Key.BACK,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[FinishEvent()],
            )
        # DEMO {
        case KeypadKeyPressAction(key=Key.UP) if set(action.pressed_keys) == {
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
        case KeypadKeyPressAction(key=Key.DOWN) if set(action.pressed_keys) == {
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
            set(action.pressed_keys)
            == {
                Key.HOME,
            }
            and set(action.held_keys) == {Key.HOME}
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

        case KeypadKeyReleaseAction(pressed_keys=(), key=Key.BACK):
            return CompleteReducerResult(
                state=state,
                events=[MenuGoBackEvent()],
            )
        case KeypadKeyReleaseAction(pressed_keys=(), key=Key.HOME):
            return CompleteReducerResult(
                state=state,
                actions=[AssistantStopListeningAction()],
                events=[MenuGoHomeEvent()],
            )

        case _:
            return state
