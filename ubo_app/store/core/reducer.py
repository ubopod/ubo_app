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
    derive_path_from_stack,
    pop_item,
    pop_stack,
    pop_to_root,
    push_application,
    push_instruction,
    push_menu,
    push_notification,
    push_prompt,
    set_page_index,
)
from ubo_app.store.core.types import (
    ApplicationStackItem,
    CloseApplicationAction,
    CloseInstructionAction,
    DeregisterRegularAppAction,
    ExecuteMenuActionAction,
    ExecuteMenuActionEvent,
    InitEvent,
    InstructionStackItem,
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
    MenuGoHomeAction,
    MenuScrollAction,
    MenuScrollDirection,
    MenuStackItem,
    MenuViewData,
    OpenApplicationAction,
    PowerOffAction,
    PowerOffEvent,
    RebootAction,
    RebootEvent,
    RegisterRegularAppAction,
    RegisterSettingAppAction,
    ReplayRecordedSequenceAction,
    ReplayRecordedSequenceEvent,
    ReportReplayingDoneAction,
    ScreenshotDataAction,
    ScreenshotDataEvent,
    ScreenshotEvent,
    SetAreEnclosuresVisibleAction,
    StackChangedEvent,
    StackPageIndexChangedEvent,
    StackPopAction,
    StackPopItemAction,
    StackPopToRootAction,
    StackPushApplicationAction,
    StackPushInstructionAction,
    StackPushMenuAction,
    StackPushNotificationAction,
    StackPushPromptAction,
    StackSetPageIndexAction,
    StoreRecordedSequenceEvent,
    TakeScreenshotAction,
    ToggleRecordingAction,
    UpdateApplicationKwargsAction,
    UpdateCurrentViewAction,
    UpdateInstructionProgressAction,
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
                recorded_sequence=(
                    *state.recorded_sequence,
                    action,
                ),
            )

    match action:
        case MenuGoBackAction():
            result = pop_stack(state)
            if result is None:
                return state
            return CompleteReducerResult(
                state=result,
                events=[StackChangedEvent(stack=result.stack)],
            )

        case MenuGoHomeAction():
            result = pop_to_root(state)
            if result is None:
                return state
            return CompleteReducerResult(
                state=result,
                events=[StackChangedEvent(stack=result.stack)],
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
            current_view = state.current_view
            if (
                not isinstance(current_view, MenuViewData)
                or current_view.total_pages <= 0
            ):
                return state
            top = state.stack[-1] if state.stack else None
            if not isinstance(top, MenuStackItem):
                return state
            if action.direction == MenuScrollDirection.UP:
                new_page = (top.page_index - 1) % current_view.total_pages
            else:
                new_page = (top.page_index + 1) % current_view.total_pages
            if new_page == top.page_index:
                return state
            page_result = set_page_index(state, new_page)
            if page_result is None:
                return state
            return CompleteReducerResult(
                state=page_result,
                events=[StackPageIndexChangedEvent(page_index=new_page)],
            )

        # =====================================================================
        # Stack Management Actions
        # =====================================================================

        case StackPushMenuAction():
            new_state = push_menu(state, action.menu_key)
            if new_state is state:
                return state  # Duplicate push, no-op
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

        case StackPushInstructionAction():
            new_state = push_instruction(
                state,
                title=action.title,
                instruction=action.instruction,
                icon=action.icon,
                spinner=action.spinner,
                timeout_seconds=action.timeout_seconds,
                footer_text=action.footer_text,
            )
            return CompleteReducerResult(
                state=new_state,
                events=[StackChangedEvent(stack=new_state.stack)],
            )

        case StackPushPromptAction():
            new_state = push_prompt(
                state,
                title=action.title,
                prompt=action.prompt,
                icon=action.icon,
                items=action.items,
            )
            return CompleteReducerResult(
                state=new_state,
                events=[StackChangedEvent(stack=new_state.stack)],
            )

        case CloseInstructionAction():
            new_stack = tuple(
                item
                for item in state.stack
                if not (
                    isinstance(item, InstructionStackItem)
                    and item.id == action.instruction_id
                )
            )
            if new_stack == state.stack:
                return state
            new_path = derive_path_from_stack(new_stack)
            new_state = replace(state, stack=new_stack, path=new_path)
            return CompleteReducerResult(
                state=new_state,
                events=[StackChangedEvent(stack=new_state.stack)],
            )

        case UpdateInstructionProgressAction():
            new_stack = tuple(
                replace(item, progress_text=action.progress_text)
                if isinstance(item, InstructionStackItem)
                and item.id == action.instruction_id
                else item
                for item in state.stack
            )
            return replace(state, stack=new_stack)

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

        case UpdateApplicationKwargsAction():
            new_stack = tuple(
                replace(
                    item,
                    initialization_kwargs={
                        **item.initialization_kwargs,
                        **action.kwargs,
                    },
                )
                if isinstance(item, ApplicationStackItem)
                and item.application_id == action.application_id
                else item
                for item in state.stack
            )
            if new_stack == state.stack:
                return state
            new_state = replace(state, stack=new_stack)
            return CompleteReducerResult(
                state=replace(
                    new_state,
                    path=derive_path_from_stack(new_stack),
                ),
                events=[StackChangedEvent(stack=new_state.stack)],
            )

        case OpenApplicationAction():
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

        case CloseApplicationAction():
            item = next(
                (
                    i
                    for i in state.stack
                    if isinstance(i, ApplicationStackItem)
                    and i.id == action.application_instance_id
                ),
                None,
            )
            if item is None:
                return state
            close_result = pop_item(state, item.id)
            if close_result is None:
                return state
            return CompleteReducerResult(
                state=close_result,
                events=[StackChangedEvent(stack=close_result.stack)],
            )

        case ToggleRecordingAction() if not state.is_replaying:
            return CompleteReducerResult(
                state=replace(
                    state,
                    is_recording=not state.is_recording,
                    recorded_sequence=(),
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

        case TakeScreenshotAction():
            return CompleteReducerResult(
                state=state,
                events=[ScreenshotEvent()],
            )

        case ScreenshotDataAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    ScreenshotDataEvent(data=action.data, hash=action.hash),
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
