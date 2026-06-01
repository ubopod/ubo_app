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
    MenuGoBackAction,
    MenuGoHomeAction,
    MenuScrollAction,
    MenuScrollDirection,
    ReplayRecordedSequenceAction,
    SnapshotEvent,
    TakeScreenshotAction,
    ToggleRecordingAction,
)
from ubo_app.store.services.assistant import (
    AssistantAction,
    AssistantStartListeningAction,
    AssistantStopListeningAction,
    KeypadTriggerSource,
    UserStopReason,
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
    KeypadReportContextAction,
    KeypadState,
)
from ubo_app.store.services.notifications import Notification, NotificationsAddAction

if TYPE_CHECKING:
    from ubo_app.store.services.audio import AudioAction

Action = KeypadAction | KeypadReportContextAction | InitAction


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
        | DisplayUpdateActivityAction
        | TakeScreenshotAction
        | MenuGoBackAction
        | MenuGoHomeAction
        | MenuScrollAction,
        FinishEvent | MenuEvent | MainEvent,
    ]
    | None
):
    """Keypad reducer."""
    if state is None:
        if isinstance(action, InitAction):
            return KeypadState()

        raise InitializationActionError(action)

    if isinstance(action, KeypadReportContextAction):
        return state(
            depth=action.depth,
            is_on_notification=action.is_on_notification,
            is_display_blanked=action.is_display_blanked,
        )

    # Cross-slice UI context (menu depth, notification/display) is mirrored into the
    # keypad slice by the service autorun (see setup.py), so the reducer stays pure and
    # reads only its own state instead of reaching into the live store mid-reduce.
    depth = state.depth
    on_notification = state.is_on_notification

    if isinstance(action, KeypadKeyPressAction):
        logger.info(
            '[Keypad] key_press: key=%s, pressed_keys=%s, depth=%d, on_notification=%s',
            action.key,
            action.pressed_keys,
            depth,
            on_notification,
        )

    # Check if this key press should wake up a blanked screen
    if (
        isinstance(action, KeypadKeyPressAction)
        and not state.is_consumed
        and state.is_display_blanked
    ):
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
        case KeypadKeyPressAction(key=Key.HOME) if depth == 1 and set(
            action.pressed_keys,
        ) == {action.key}:
            return CompleteReducerResult(
                state=state,
                actions=[
                    DisplayUpdateActivityAction(),
                    AssistantStartListeningAction(
                        source=KeypadTriggerSource(key=Key.HOME, mode='press'),
                    ),
                ],
            )
        case KeypadKeyReleaseAction(pressed_keys=(), key=Key.HOME) if depth == 1:
            return CompleteReducerResult(
                state=state,
                actions=[
                    AssistantStopListeningAction(
                        reason=UserStopReason(
                            source=KeypadTriggerSource(
                                key=Key.HOME,
                                mode='press',
                            ),
                        ),
                    ),
                ],
            )
        # L1/L2/L3 emit MenuChooseByIndexEvent unconditionally; the notification/menu
        # handler bounds-checks the index and no-ops when that slot has no item, so the
        # reducer needn't know notification item presence.
        case KeypadKeyPressAction(key=Key.L1) if set(action.pressed_keys) == {
            action.key,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[MenuChooseByIndexEvent(index=0)],
            )
        case KeypadKeyPressAction(key=Key.L2) if set(action.pressed_keys) == {
            action.key,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[MenuChooseByIndexEvent(index=1)],
            )
        case KeypadKeyPressAction(key=Key.L3) if set(action.pressed_keys) == {
            action.key,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction()],
                events=[MenuChooseByIndexEvent(index=2)],
            )
        case KeypadKeyPressAction(key=Key.UP) if set(action.pressed_keys) == {
            action.key,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[
                    DisplayUpdateActivityAction(),
                    MenuScrollAction(direction=MenuScrollDirection.UP),
                ],
            )
        case KeypadKeyPressAction(key=Key.DOWN) if set(action.pressed_keys) == {
            action.key,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[
                    DisplayUpdateActivityAction(),
                    MenuScrollAction(direction=MenuScrollDirection.DOWN),
                ],
            )
        case KeypadKeyPressAction(key=Key.L1) if set(action.pressed_keys) == {
            Key.HOME,
            Key.L1,
        }:
            return CompleteReducerResult(
                state=state,
                actions=[DisplayUpdateActivityAction(), TakeScreenshotAction()],
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
                actions=[
                    AssistantStartListeningAction(
                        source=KeypadTriggerSource(key=Key.HOME, mode='hold'),
                    ),
                ],
            )

        case KeypadKeyUnholdAction(key=Key.HOME):
            return CompleteReducerResult(
                state=state(is_consumed=True),
                actions=[
                    AssistantStopListeningAction(
                        reason=UserStopReason(
                            source=KeypadTriggerSource(
                                key=Key.HOME,
                                mode='hold',
                            ),
                        ),
                    ),
                ],
            )

        case KeypadKeyReleaseAction() if state.is_consumed:
            return state(is_consumed=False)

        case KeypadKeyReleaseAction(pressed_keys=(), key=Key.BACK):
            return CompleteReducerResult(
                state=state,
                actions=[MenuGoBackAction()],
            )
        case KeypadKeyReleaseAction(pressed_keys=(), key=Key.HOME):
            return CompleteReducerResult(
                state=state,
                actions=[
                    AssistantStopListeningAction(
                        reason=UserStopReason(
                            source=KeypadTriggerSource(
                                key=Key.HOME,
                                mode='press',
                            ),
                        ),
                    ),
                    MenuGoHomeAction(),
                ],
            )

        case _:
            return state
