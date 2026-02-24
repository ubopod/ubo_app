# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace
from typing import cast

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)
from ubo_gui.menu.types import menu_items

from ubo_app.store.core.constants import compute_total_pages
from ubo_app.store.core.menu_adapter import (
    get_current_menu_from_stack,
    item_to_menu_item_data,
)
from ubo_app.store.core.menu_registration import (
    deregister_regular_app,
    register_regular_app,
    register_setting_app,
    update_service_status,
)
from ubo_app.store.core.menus import HOME_MENU
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
    ApplicationStackItem,
    ApplicationViewData,
    CloseApplicationAction,
    CloseApplicationEvent,
    DeregisterRegularAppAction,
    ExecuteMenuActionAction,
    HomeViewData,
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
    MenuStackItem,
    MenuViewData,
    NotificationStackItem,
    NotificationViewData,
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
    ViewData,
)
from ubo_app.store.settings.types import SettingsServiceSetStatusAction

# =============================================================================
# View Computation for Dumb UI Architecture
# =============================================================================


# convert_item_to_menu_item_data is now in menu_adapter.py as item_to_menu_item_data


def compute_view_from_stack(
    state: MainState,
) -> ViewData:
    """Compute the ViewData from the current stack and menu state.

    This is the core function for the dumb UI architecture.
    It determines what the UI should render based on the Redux state.
    """
    stack = state.stack
    menu = state.menu

    if not stack:
        # Empty stack - return home view with empty data
        return HomeViewData()

    top_item = stack[-1]

    # Handle different stack item types
    if isinstance(top_item, ApplicationStackItem):
        # Convert initialization_kwargs to extra_data for logging
        extra_data: dict[str, str] = {}
        for k, v in top_item.initialization_kwargs.items():
            extra_data[k] = str(v)
        return ApplicationViewData(
            application_id=top_item.application_id,
            show_status_bar=False,
            extra_data=extra_data,
        )

    if isinstance(top_item, NotificationStackItem):
        return NotificationViewData(
            notification_id=top_item.notification_id,
            show_status_bar=False,
        )

    # Must be MenuStackItem - compute menu view
    if not isinstance(top_item, MenuStackItem):
        return HomeViewData()

    # Get the current menu based on stack
    current_menu = get_current_menu_from_stack(menu, stack)
    if current_menu is None:
        return HomeViewData()

    # Get menu items
    items = menu_items(current_menu)
    page_index = top_item.page_index

    # Convert items to MenuItemData
    menu_item_data = tuple(
        item_to_menu_item_data(item, i) for i, item in enumerate(items)
    )

    # Determine title, heading, and sub_heading
    title_value = current_menu.title
    title = title_value() if callable(title_value) else (title_value or '')

    # Extract heading and sub_heading for HeadedMenu
    heading: str | None = None
    sub_heading: str | None = None
    heading_val = getattr(current_menu, 'heading', None)
    if heading_val is not None:
        heading = str(heading_val() if callable(heading_val) else heading_val)
    sub_heading_val = getattr(current_menu, 'sub_heading', None)
    if sub_heading_val is not None:
        sub_heading = str(
            sub_heading_val() if callable(sub_heading_val) else sub_heading_val,
        )

    # Calculate total pages (HeadedMenu heading+sub_heading occupy visual slots)
    total_pages = compute_total_pages(len(items), is_headed=heading is not None)

    # Determine if at home (depth 1) or in a submenu
    depth = len([i for i in stack if isinstance(i, MenuStackItem)])
    is_home = depth <= 1

    if is_home:
        # Home view shows special layout with gauges, volume
        # Filter out None items for HomeViewData
        home_items = tuple(item for item in menu_item_data if item is not None)
        return HomeViewData(
            show_status_bar=True,
            menu_items=home_items,
            # CPU/RAM/volume are updated separately via other state
            cpu_percent=0.0,
            ram_percent=0.0,
            volume_level=0.0,
        )

    # Standard menu view
    return MenuViewData(
        show_status_bar=page_index == 0,  # Show status bar only on first page
        title=cast('str', title),
        heading=heading,
        sub_heading=sub_heading,
        items=menu_item_data,
        page_index=page_index,
        total_pages=total_pages,
    )


def reducer(
    state: MainState | None,
    action: MainAction,
) -> ReducerResult[MainState, None, InitEvent | MainEvent]:
    if state is None:
        if isinstance(action, InitAction):
            return MainState(
                menu=HOME_MENU,
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
            new_view = compute_view_from_stack(new_state)
            new_state = replace(new_state, current_view=new_view)
            return CompleteReducerResult(
                state=new_state,
                events=[
                    StackChangedEvent(stack=new_state.stack),
                    ViewChangedEvent(view=new_view),
                ],
            )

        case StackPushApplicationAction():
            new_state = push_application(
                state,
                action.application_id,
                action.initialization_args,
                action.initialization_kwargs,
            )
            new_view = compute_view_from_stack(new_state)
            new_state = replace(new_state, current_view=new_view)
            return CompleteReducerResult(
                state=new_state,
                events=[
                    StackChangedEvent(stack=new_state.stack),
                    ViewChangedEvent(view=new_view),
                ],
            )

        case StackPushNotificationAction():
            new_state = push_notification(state, action.notification_id)
            new_view = compute_view_from_stack(new_state)
            new_state = replace(new_state, current_view=new_view)
            return CompleteReducerResult(
                state=new_state,
                events=[
                    StackChangedEvent(stack=new_state.stack),
                    ViewChangedEvent(view=new_view),
                ],
            )

        case StackPopAction():
            result = pop_stack(state, action.count)
            if result is None:
                return state  # Can't pop root
            new_state = result
            new_view = compute_view_from_stack(new_state)
            new_state = replace(new_state, current_view=new_view)
            return CompleteReducerResult(
                state=new_state,
                events=[
                    StackChangedEvent(stack=new_state.stack),
                    ViewChangedEvent(view=new_view),
                ],
            )

        case StackPopToRootAction():
            result = pop_to_root(state)
            if result is None:
                return state  # Already at root
            new_state = result
            new_view = compute_view_from_stack(new_state)
            new_state = replace(new_state, current_view=new_view)
            return CompleteReducerResult(
                state=new_state,
                events=[
                    StackChangedEvent(stack=new_state.stack),
                    ViewChangedEvent(view=new_view),
                ],
            )

        case StackPopItemAction():
            result = pop_item(state, action.item_id)
            if result is None:
                return state  # Item not found, no change
            new_state = result
            new_view = compute_view_from_stack(new_state)
            new_state = replace(new_state, current_view=new_view)
            return CompleteReducerResult(
                state=new_state,
                events=[
                    StackChangedEvent(stack=new_state.stack),
                    ViewChangedEvent(view=new_view),
                ],
            )

        case StackSetPageIndexAction():
            result = set_page_index(state, action.page_index)
            if result is None:
                return state
            new_state = result
            new_view = compute_view_from_stack(new_state)
            new_state = replace(new_state, current_view=new_view)
            return CompleteReducerResult(
                state=new_state,
                events=[
                    StackPageIndexChangedEvent(page_index=action.page_index),
                    ViewChangedEvent(view=new_view),
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
            # This allows ViewRenderer to push computed views that include dynamic menus
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
            # Execute a menu action by its action_id
            # This is handled synchronously - the handler may dispatch other actions
            from ubo_app.store.core.action_registry import execute_action

            execute_action(action.action_id)
            return state

        case _:
            return state
