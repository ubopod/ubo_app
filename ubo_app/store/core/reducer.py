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
    pop_chat,
    pop_item,
    pop_notification,
    pop_stack,
    pop_to_root,
    push_application,
    push_chat,
    push_instruction,
    push_menu,
    push_notification,
    push_prompt,
    push_render,
    set_page_index,
)
from ubo_app.store.core.types import (
    ApplicationScrollEvent,
    ApplicationStackItem,
    ApplicationViewData,
    ChatStackItem,
    ChatViewData,
    CloseApplicationAction,
    CloseInstructionAction,
    DeregisterRegularAppAction,
    ExecuteMenuActionAction,
    ExecuteMenuActionEvent,
    InitEvent,
    InstructionStackItem,
    LocalOverlayGoBackEvent,
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
    NotificationStackItem,
    NotificationViewData,
    OpenApplicationAction,
    OpenRenderAction,
    PowerOffAction,
    PowerOffEvent,
    PromptStackItem,
    RebootAction,
    RebootEvent,
    RegisterRegularAppAction,
    RegisterSettingAppAction,
    RenderStackItem,
    RenderViewData,
    ReplayRecordedSequenceAction,
    ReplayRecordedSequenceEvent,
    ReportReplayingDoneAction,
    ScreenshotDataAction,
    ScreenshotDataEvent,
    ScreenshotEvent,
    SetAreEnclosuresVisibleAction,
    SetLocalOverlayOpenAction,
    StackChangedEvent,
    StackPageIndexChangedEvent,
    StackPopAction,
    StackPopChatAction,
    StackPopItemAction,
    StackPopNotificationAction,
    StackPopToRootAction,
    StackPushApplicationAction,
    StackPushChatAction,
    StackPushInstructionAction,
    StackPushMenuAction,
    StackPushNotificationAction,
    StackPushPromptAction,
    StackPushRenderAction,
    StackSetPageIndexAction,
    StoreRecordedSequenceEvent,
    TakeScreenshotAction,
    ToggleRecordingAction,
    UpdateApplicationKwargsAction,
    UpdateCurrentViewAction,
    UpdateInstructionProgressAction,
    UpdatePromptAction,
    UpdateRenderPropsAction,
    ViewChangedEvent,
)
from ubo_app.store.services.chat import ChatEndSessionAction
from ubo_app.store.services.keypad import KeypadAction
from ubo_app.store.services.notifications import NotificationsClearByIdAction
from ubo_app.store.settings.types import SettingsServiceSetStatusAction


def reducer(
    state: MainState | None,
    action: MainAction,
) -> ReducerResult[
    MainState,
    NotificationsClearByIdAction | ChatEndSessionAction,
    InitEvent | MainEvent,
]:
    if state is None:
        if isinstance(action, InitAction):
            return MainState(
                stack=create_root_stack_item(),
            )
        raise InitializationActionError(action)

    if state.is_recording and isinstance(action, KeypadAction):
        state = replace(
            state,
            recorded_sequence=(
                *state.recorded_sequence,
                action,
            ),
        )

    match action:
        case MenuGoBackAction():
            if state.is_local_overlay_open:
                # A GUI-local overlay (e.g. the notification extra-information
                # page) owns the screen but isn't on this stack. BACK must
                # close THAT, not pop here — delegate to the GUI and clear the
                # flag. If the overlay is already gone (stale flag), the client
                # re-issues a normal BACK, which now pops (self-healing).
                return CompleteReducerResult(
                    state=replace(state, is_local_overlay_open=False),
                    events=[LocalOverlayGoBackEvent()],
                )
            result = pop_stack(state)
            return _complete_stack_pop_result(result, fallback=state)

        case SetLocalOverlayOpenAction():
            if state.is_local_overlay_open == action.is_open:
                return state
            return replace(state, is_local_overlay_open=action.is_open)

        case MenuGoHomeAction():
            result = pop_to_root(state)
            return _complete_stack_pop_result(result, fallback=state)

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
            total_pages = 1
            if isinstance(
                current_view,
                (ApplicationViewData, RenderViewData, ChatViewData),
            ):
                # The chat overlay scrolls like an application view: the
                # GUI client owns the pixel scroll offset (it needs
                # rendered bubble heights), so ↑/↓ just emit a scroll
                # event for the renderer to pan its content.
                direction = (
                    'up'
                    if action.direction == MenuScrollDirection.UP
                    else 'down'
                )
                return CompleteReducerResult(
                    state=state,
                    events=[ApplicationScrollEvent(direction=direction)],
                )
            if isinstance(current_view, NotificationViewData):
                if current_view.total_pages <= 1:
                    # Single-page notification — text may overflow; emit scroll
                    # event so the GUI can adjust the slider-based text scroll.
                    direction = (
                        'up'
                        if action.direction == MenuScrollDirection.UP
                        else 'down'
                    )
                    return CompleteReducerResult(
                        state=state,
                        events=[ApplicationScrollEvent(direction=direction)],
                    )
                total_pages = current_view.total_pages
            elif isinstance(current_view, MenuViewData):
                total_pages = current_view.total_pages
            else:
                return state
            if total_pages <= 1:
                return state
            top = state.stack[-1] if state.stack else None
            if not isinstance(top, (MenuStackItem, NotificationStackItem)):
                return state
            if action.direction == MenuScrollDirection.UP:
                new_page = (top.page_index - 1) % total_pages
            else:
                new_page = (top.page_index + 1) % total_pages
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
            return _complete_stack_result(new_state, fallback=state)

        case StackPushRenderAction():
            new_state = push_render(
                state,
                action.kind,
                title=action.title,
                props=action.props,
                items=action.items,
                stream_id=action.stream_id,
            )
            return _complete_stack_result(new_state, fallback=state)

        case StackPushNotificationAction():
            new_state = push_notification(state, action.notification_id)
            return _complete_stack_result(new_state, fallback=state)

        case StackPopNotificationAction():
            new_state = pop_notification(state, action.notification_id)
            return _complete_stack_result(new_state, fallback=state)

        case StackPushChatAction():
            new_state = push_chat(state, action.session_id)
            return _complete_stack_result(new_state, fallback=state)

        case StackPopChatAction():
            new_state = pop_chat(state)
            return _complete_stack_result(new_state, fallback=state)

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
            return _complete_stack_result(new_state, fallback=state)

        case StackPushPromptAction():
            new_state = push_prompt(
                state,
                title=action.title,
                prompt=action.prompt,
                icon=action.icon,
                items=action.items,
            )
            return _complete_stack_result(new_state, fallback=state)

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
            return _complete_stack_pop_result(result, fallback=state)

        case StackPopToRootAction():
            result = pop_to_root(state)
            return _complete_stack_pop_result(result, fallback=state)

        case StackPopItemAction():
            result = pop_item(state, action.item_id)
            return _complete_stack_pop_result(result, fallback=state)

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

        case UpdateRenderPropsAction():
            new_stack = tuple(
                replace(
                    item,
                    kind=action.next_kind or item.kind,
                    title=action.title or item.title,
                    props=action.props
                    if action.next_kind and action.next_kind != item.kind
                    else {
                        **item.props,
                        **action.props,
                    },
                )
                if isinstance(item, RenderStackItem)
                and (
                    (action.stream_id and item.stream_id == action.stream_id)
                    or (action.kind and item.kind == action.kind)
                )
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

        case UpdatePromptAction():
            new_stack = tuple(
                replace(
                    item,
                    title=action.title or item.title,
                    prompt=action.prompt or item.prompt,
                    icon=action.icon or item.icon,
                    items=action.items if action.items is not None else item.items,
                )
                if isinstance(item, PromptStackItem)
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
            return _complete_stack_result(new_state, fallback=state)

        case OpenRenderAction():
            new_state = push_render(
                state,
                action.kind,
                title=action.title,
                props=action.props,
                items=action.items,
                stream_id=action.stream_id,
            )
            return _complete_stack_result(new_state, fallback=state)

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
            return _complete_stack_result(close_result, fallback=state)

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


def _complete_stack_result(
    state: MainState | None,
    *,
    fallback: MainState,
) -> (
    MainState
    | CompleteReducerResult[MainState, NotificationsClearByIdAction, MainEvent]
):
    """Return a standard stack-change reducer result."""
    if state is None:
        return fallback
    return CompleteReducerResult(
        state=state,
        events=[StackChangedEvent(stack=state.stack)],
    )


def _complete_stack_pop_result(
    state: MainState | None,
    *,
    fallback: MainState,
) -> (
    MainState
    | CompleteReducerResult[
        MainState,
        NotificationsClearByIdAction | ChatEndSessionAction,
        MainEvent,
    ]
):
    """Return a stack-pop result, clearing notifications removed from the stack.

    Generic pop paths (``MenuGoBack``, ``StackPop``, ``StackPopToRoot``,
    ``StackPopItem``) can remove a ``NotificationStackItem`` whose
    backing entry is still in ``state.notifications`` — e.g. the user
    presses ``back`` on a notification rather than dismissing it via its
    own dismiss button. Without this, ``state.notifications`` drifts out
    of sync with the navigation stack and the notification's
    ``on_close_id`` callback (fired by the ``NotificationsClearEvent``
    handler in ``menu_event_handlers``) never runs, so downstream
    services that rely on it for cleanup (e.g. the camera service's
    input queue) stall.

    The dedicated ``NotificationsClearAction`` / ``ClearByIdAction``
    paths don't use this helper — they already update
    ``state.notifications`` before dispatching their stack pop.

    Same idea for the chat overlay: a generic pop (e.g. ``MenuGoBack``)
    removes the ``ChatStackItem`` but leaves ``ChatState.is_active``
    True and the chat service's in-flight dismiss timer running.
    Dispatching ``ChatEndSessionAction`` here fires
    ``ChatSessionEndedEvent``, which the chat service's voice handler
    uses to cancel its dismiss timer and (when the dismiss is *not*
    self-initiated by its own timer) stop the assistant — so "Back"
    cleanly tears down the whole conversation. The chat overlay is a
    singleton on the stack, so this collapses to a single boolean
    check.
    """
    if state is None:
        return fallback
    removed_notification_ids = {
        item.notification_id
        for item in fallback.stack
        if isinstance(item, NotificationStackItem)
    } - {
        item.notification_id
        for item in state.stack
        if isinstance(item, NotificationStackItem)
    }
    had_chat = any(
        isinstance(item, ChatStackItem) for item in fallback.stack
    ) and not any(
        isinstance(item, ChatStackItem) for item in state.stack
    )
    actions: list[NotificationsClearByIdAction | ChatEndSessionAction] = [
        NotificationsClearByIdAction(id=notification_id)
        for notification_id in removed_notification_ids
    ]
    if had_chat:
        actions.append(ChatEndSessionAction())
    return CompleteReducerResult(
        state=state,
        actions=actions,
        events=[StackChangedEvent(stack=state.stack)],
    )
