# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.core.menu_registration import (
    deregister_regular_app,
    register_regular_app,
    register_setting_app,
    update_service_status,
)
from ubo_app.store.core.stack_ops import (
    create_root_stack_item,
    pop_item,
    pop_stack,
    pop_to_root,
    push_application,
    push_menu,
    push_notification,
    set_page_index,
)
from ubo_app.store.core.types import (
    CloseApplicationAction,
    CloseApplicationEvent,
    DeregisterRegularAppAction,
    ExecuteMenuActionAction,
    ExecuteMenuActionEvent,
    InitEvent,
    MainAction,
    MainEvent,
    MainState,
    MenuChooseByIconAction,
    MenuChooseByIconEvent,
    MenuChooseByIndexAction,
    MenuChooseByIndexEvent,
    MenuChooseByLabelAction,
    MenuChooseByLabelEvent,
    MenuGoBackAction,
    MenuGoBackEvent,
    MenuGoHomeAction,
    MenuGoHomeEvent,
    MenuScrollAction,
    MenuScrollEvent,
    OpenApplicationAction,
    OpenApplicationEvent,
    PowerOffAction,
    PowerOffEvent,
    RebootAction,
    RebootEvent,
    RegisterRegularAppAction,
    RegisterSettingAppAction,
    ReplayRecordedSequenceAction,
    ReplayRecordedSequenceEvent,
    ReportReplayingDoneAction,
    SetAreEnclosuresVisibleAction,
    StackChangedEvent,
    StackPageIndexChangedEvent,
    StackPopAction,
    StackPopItemAction,
    StackPopToRootAction,
    StackPushApplicationAction,
    StackPushMenuAction,
    StackPushNotificationAction,
    StackSetPageIndexAction,
    StoreRecordedSequenceEvent,
    ToggleRecordingAction,
    UpdateCurrentViewAction,
    ViewChangedEvent,
)
from ubo_app.store.settings.types import SettingsServiceSetStatusAction


def reducer(
    state: MainState | None,
    action: MainAction,
) -> ReducerResult[MainState, None, InitEvent | MainEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return MainState(
                stack=create_root_stack_item(),
            )
        raise InitializationActionError(action)

    if state.is_recording:
        from ubo_app.store.services.keypad import KeypadAction

        if isinstance(action, KeypadAction):
            state = replace(
                state,
                recorded_sequence=[
                    *state.recorded_sequence,
                    action,
                ],
            )

    match action:
        case MenuGoBackAction():
            return CompleteReducerResult(
                state=state,
                events=[MenuGoBackEvent()],
            )

        case MenuGoHomeAction():
            return CompleteReducerResult(
                state=state,
                events=[MenuGoHomeEvent()],
            )

        case MenuChooseByIconAction():
            return CompleteReducerResult(
                state=state,
                events=[MenuChooseByIconEvent(icon=action.icon)],
            )

        case MenuChooseByLabelAction():
            return CompleteReducerResult(
                state=state,
                events=[MenuChooseByLabelEvent(label=action.label)],
            )

        case MenuChooseByIndexAction():
            return CompleteReducerResult(
                state=state,
                events=[MenuChooseByIndexEvent(index=action.index)],
            )

        case MenuScrollAction():
            return CompleteReducerResult(
                state=state,
                events=[MenuScrollEvent(direction=action.direction)],
            )

        # =====================================================================
        # Stack Management Actions
        # =====================================================================

        case StackPushMenuAction():
            new_state = push_menu(state, action.menu_key)
            return CompleteReducerResult(
                state=new_state,
                events=[StackChangedEvent(stack=new_state.stack)],
            )

        case StackPushApplicationAction():
            new_state = push_application(
                state,
                action.application_id,
                action.initialization_args,
                action.initialization_kwargs,
            )
            return CompleteReducerResult(
                state=new_state,
                events=[StackChangedEvent(stack=new_state.stack)],
            )

        case StackPushNotificationAction():
            new_state = push_notification(state, action.notification_id)
            return CompleteReducerResult(
                state=new_state,
                events=[StackChangedEvent(stack=new_state.stack)],
            )

        case StackPopAction():
            result = pop_stack(state, action.count)
            if result is None:
                return state  # Can't pop root
            new_state = result
            return CompleteReducerResult(
                state=new_state,
                events=[StackChangedEvent(stack=new_state.stack)],
            )

        case StackPopToRootAction():
            result = pop_to_root(state)
            if result is None:
                return state  # Already at root
            new_state = result
            return CompleteReducerResult(
                state=new_state,
                events=[StackChangedEvent(stack=new_state.stack)],
            )

        case StackPopItemAction():
            result = pop_item(state, action.item_id)
            if result is None:
                return state  # Item not found, no change
            new_state = result
            return CompleteReducerResult(
                state=new_state,
                events=[StackChangedEvent(stack=new_state.stack)],
            )

        case StackSetPageIndexAction():
            result = set_page_index(state, action.page_index)
            if result is None:
                return state
            new_state = result
            return CompleteReducerResult(
                state=new_state,
                events=[
                    StackPageIndexChangedEvent(page_index=action.page_index),
                ],
            )

        case OpenApplicationAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    OpenApplicationEvent(
                        application_id=action.application_id,
                        initialization_args=action.initialization_args,
                        initialization_kwargs=action.initialization_kwargs,
                    ),
                ],
            )

        case CloseApplicationAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    CloseApplicationEvent(
                        application_instance_id=action.application_instance_id,
                    ),
                ],
            )

        case ToggleRecordingAction() if not state.is_replaying:
            return CompleteReducerResult(
                state=replace(
                    state,
                    is_recording=not state.is_recording,
                    recorded_sequence=[],
                ),
                events=[
                    StoreRecordedSequenceEvent(
                        recorded_sequence=state.recorded_sequence,
                    ),
                ]
                if state.is_recording
                else [],
            )

        case ReplayRecordedSequenceAction() if (
            not state.is_recording and not state.is_replaying
        ):
            return CompleteReducerResult(
                state=replace(state, is_replaying=True),
                events=[ReplayRecordedSequenceEvent()],
            )

        case ReportReplayingDoneAction():
            return replace(state, is_replaying=False)

        case RegisterSettingAppAction():
            return register_setting_app(state, action)

        case RegisterRegularAppAction():
            return register_regular_app(state, action)

        case DeregisterRegularAppAction():
            new_state, events = deregister_regular_app(state, action)
            if events:
                return CompleteReducerResult(state=new_state, events=events)
            return new_state

        case SetAreEnclosuresVisibleAction():
            return replace(
                state,
                is_header_visible=action.is_header_visible,
                is_footer_visible=action.is_footer_visible,
            )

        case PowerOffAction():
            return CompleteReducerResult(
                state=state,
                events=[PowerOffEvent()],
            )

        case RebootAction():
            return CompleteReducerResult(
                state=state,
                events=[RebootEvent()],
            )

        case SettingsServiceSetStatusAction() if action.is_active is False:
            new_state, events = update_service_status(state, action)
            if events:
                return CompleteReducerResult(state=new_state, events=events)
            return new_state

        case UpdateCurrentViewAction():
            # Update current_view with a computed view (used by dynamic menu system)
            view_unchanged = state.current_view == action.view
            status_unchanged = state.status_bar == action.status_bar
            if view_unchanged and status_unchanged:
                return state  # No change
            return CompleteReducerResult(
                state=replace(
                    state,
                    current_view=action.view,
                    status_bar=action.status_bar,
                ),
                events=[
                    ViewChangedEvent(
                        view=action.view,
                        status_bar=action.status_bar,
                    ),
                ],
            )

        case ExecuteMenuActionAction():
            # Emit event for the side-effect layer to handle
            return CompleteReducerResult(
                state=state,
                events=[
                    ExecuteMenuActionEvent(
                        action_id=action.action_id,
                        menu_key=action.menu_key,
                    ),
                ],
            )

        case _:
            return state
