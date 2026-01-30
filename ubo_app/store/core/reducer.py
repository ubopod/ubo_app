# ruff: noqa: D100, D103
from __future__ import annotations

import uuid
from dataclasses import replace
from typing import TYPE_CHECKING, cast

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)
from ubo_gui.menu.types import Item, Menu, SubMenuItem, menu_items

from ubo_app.store.core.menus import HOME_MENU
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
    MenuItemData,
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
    SetMenuPathAction,
    StackChangedEvent,
    StackItemType,
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

if TYPE_CHECKING:
    from collections.abc import Sequence


def find_sub_menu_item(items: Sequence[Item], key: str) -> SubMenuItem:
    item = next((item for item in items if item.key == key), None)
    if not isinstance(item, SubMenuItem):
        msg = f'{key.capitalize()} menu item is not a `SubMenuItem`'
        raise TypeError(msg)
    return item


def find_menu_for_item(items: Sequence[Item], key: str) -> Menu | None:
    """Find the menu for an item by key.

    Handles both SubMenuItem (with sub_menu) and ActionItem (with action that
    returns a menu or a callable that returns a menu). Returns None if no menu
    can be found.
    """
    from ubo_gui.menu.types import ActionItem

    item = next((item for item in items if item.key == key), None)
    if item is None:
        return None

    # Handle SubMenuItem - has sub_menu attribute
    if isinstance(item, SubMenuItem):
        sub_menu = item.sub_menu
        return sub_menu() if callable(sub_menu) else sub_menu

    # Handle ActionItem - action may return a menu or callable that returns menu
    if isinstance(item, ActionItem) and item.action:
        try:
            result = item.action()
            # If result is callable (e.g., autorun wrapper), call it to get menu
            if callable(result):
                result = result()
            # Check if result is a Menu (HeadedMenu, HeadlessMenu, etc.)
            if hasattr(result, 'items') and hasattr(result, 'title'):
                return result
        except Exception:  # noqa: BLE001, S110
            # Action failed or didn't return a menu - silently ignore
            pass

    return None


# =============================================================================
# Stack Helper Functions
# =============================================================================


def derive_path_from_stack(stack: tuple[StackItemType, ...]) -> list[str]:
    """Derive the menu path from the stack.

    Returns a list of menu keys representing the navigation path.
    Only MenuStackItems contribute to the path (apps and notifications don't).
    """
    return [item.menu_key for item in stack if isinstance(item, MenuStackItem)][1:]


def get_current_menu_from_stack(
    root_menu: Menu | None,
    stack: tuple[StackItemType, ...],
) -> Menu | None:
    """Traverse menu tree based on stack to get current menu.

    This follows the stack path to find the menu currently at the top.
    Only works when the top of stack is a MenuStackItem.
    """
    if not root_menu or not stack:
        return None

    # Only consider MenuStackItems for menu traversal
    menu_path = [item for item in stack if isinstance(item, MenuStackItem)]
    if not menu_path:
        return None

    current_menu: Menu | None = root_menu
    for item in menu_path[1:]:  # Skip root
        if current_menu is None:
            return None
        items = menu_items(current_menu)
        # Use find_menu_for_item which handles both SubMenuItem and ActionItem
        current_menu = find_menu_for_item(items, item.menu_key)
        if current_menu is None:
            return None
    return current_menu


def create_root_stack_item() -> tuple[MenuStackItem]:
    """Create the initial root stack item for the home menu."""
    return (
        MenuStackItem(
            id=uuid.uuid4().hex,
            menu_key='',  # Root has empty key
            page_index=0,
        ),
    )


# =============================================================================
# View Computation for Dumb UI Architecture
# =============================================================================


def convert_item_to_menu_item_data(
    item: Item | None,
    index: int,
) -> MenuItemData | None:
    """Convert a ubo_gui Item to a MenuItemData for rendering.

    Returns None if the input item is None (placeholder slot).
    """
    if item is None:
        return None

    # Determine action_id based on item type
    action_id: str | None = None
    key_val = getattr(item, 'key', None)
    if key_val and isinstance(key_val, str):
        action_id = f'menu:select:{key_val}'

    # Get values with safe defaults, handling callables
    key: str = f'item_{index}'
    if key_val:
        key = key_val if isinstance(key_val, str) else f'item_{index}'

    label_val = getattr(item, 'label', '')
    label = label_val() if callable(label_val) else (label_val or '')

    icon_val = getattr(item, 'icon', '')
    icon = icon_val() if callable(icon_val) else (icon_val or '')

    # Handle background_color
    bg_color_val = getattr(item, 'background_color', None)
    bg_color: str | None = None
    if isinstance(bg_color_val, str):
        bg_color = bg_color_val

    # Handle icon_color
    icon_color = '#ffffff'
    icon_color_val = getattr(item, 'icon_color', None)
    if icon_color_val:
        if callable(icon_color_val):
            resolved = icon_color_val()
            if isinstance(resolved, str):
                icon_color = resolved
        elif isinstance(icon_color_val, str):
            icon_color = icon_color_val

    # Handle is_short - could be bool or callable
    is_short_val = getattr(item, 'is_short', False)
    is_short = is_short_val if isinstance(is_short_val, bool) else False

    return MenuItemData(
        key=key,
        label=str(label),
        icon=str(icon),
        color=icon_color,
        is_short=is_short,
        background_color=bg_color,
        action_id=action_id,
    )


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
        convert_item_to_menu_item_data(item, i) for i, item in enumerate(items)
    )

    # Determine title
    title_value = current_menu.title
    title = title_value() if callable(title_value) else (title_value or '')

    # Calculate total pages (PAGE_SIZE = 3 items per page)
    page_size = 3
    total_pages = max(1, (len(items) + page_size - 1) // page_size)

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
            new_item = MenuStackItem(
                id=uuid.uuid4().hex,
                menu_key=action.menu_key,
                page_index=0,
            )
            new_stack = (*state.stack, new_item)
            new_path = derive_path_from_stack(new_stack)
            new_state = replace(
                state,
                stack=new_stack,
                path=new_path,
                depth=len(new_stack),
            )
            # Compute new view from updated state
            new_view = compute_view_from_stack(new_state)
            new_state = replace(new_state, current_view=new_view)
            return CompleteReducerResult(
                state=new_state,
                events=[
                    StackChangedEvent(stack=new_stack),
                    ViewChangedEvent(view=new_view),
                ],
            )

        case StackPushApplicationAction():
            new_item = ApplicationStackItem(
                id=uuid.uuid4().hex,
                application_id=action.application_id,
                initialization_args=action.initialization_args,
                initialization_kwargs=action.initialization_kwargs,
            )
            new_stack = (*state.stack, new_item)
            new_state = replace(
                state,
                stack=new_stack,
                depth=len(new_stack),
            )
            new_view = compute_view_from_stack(new_state)
            new_state = replace(new_state, current_view=new_view)
            return CompleteReducerResult(
                state=new_state,
                events=[
                    StackChangedEvent(stack=new_stack),
                    ViewChangedEvent(view=new_view),
                ],
            )

        case StackPushNotificationAction():
            new_item = NotificationStackItem(
                id=uuid.uuid4().hex,
                notification_id=action.notification_id,
            )
            new_stack = (*state.stack, new_item)
            new_state = replace(
                state,
                stack=new_stack,
                depth=len(new_stack),
            )
            new_view = compute_view_from_stack(new_state)
            new_state = replace(new_state, current_view=new_view)
            return CompleteReducerResult(
                state=new_state,
                events=[
                    StackChangedEvent(stack=new_stack),
                    ViewChangedEvent(view=new_view),
                ],
            )

        case StackPopAction():
            if len(state.stack) <= 1:
                return state  # Can't pop root
            # Pop 'count' items but always keep at least root
            pop_count = min(action.count, len(state.stack) - 1)
            new_stack = state.stack[:-pop_count] if pop_count > 0 else state.stack
            new_path = derive_path_from_stack(new_stack)
            new_state = replace(
                state,
                stack=new_stack,
                path=new_path,
                depth=len(new_stack),
            )
            new_view = compute_view_from_stack(new_state)
            new_state = replace(new_state, current_view=new_view)
            return CompleteReducerResult(
                state=new_state,
                events=[
                    StackChangedEvent(stack=new_stack),
                    ViewChangedEvent(view=new_view),
                ],
            )

        case StackPopToRootAction():
            if len(state.stack) <= 1:
                return state  # Already at root
            new_stack = state.stack[:1]
            new_state = replace(
                state,
                stack=new_stack,
                path=[],
                depth=1,
            )
            new_view = compute_view_from_stack(new_state)
            new_state = replace(new_state, current_view=new_view)
            return CompleteReducerResult(
                state=new_state,
                events=[
                    StackChangedEvent(stack=new_stack),
                    ViewChangedEvent(view=new_view),
                ],
            )

        case StackPopItemAction():
            # Find and remove the specific item from stack
            new_stack = tuple(item for item in state.stack if item.id != action.item_id)
            if new_stack == state.stack:
                return state  # Item not found, no change
            new_path = derive_path_from_stack(new_stack)
            new_state = replace(
                state,
                stack=new_stack,
                path=new_path,
                depth=len(new_stack),
            )
            new_view = compute_view_from_stack(new_state)
            new_state = replace(new_state, current_view=new_view)
            return CompleteReducerResult(
                state=new_state,
                events=[
                    StackChangedEvent(stack=new_stack),
                    ViewChangedEvent(view=new_view),
                ],
            )

        case StackSetPageIndexAction():
            if not state.stack:
                return state
            top = state.stack[-1]
            if not isinstance(top, MenuStackItem):
                return state  # Can only set page index for menu items
            new_top = replace(top, page_index=action.page_index)
            new_stack = (*state.stack[:-1], new_top)
            new_state = replace(state, stack=new_stack)
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
            menu = state.menu
            if not menu or not action.service:
                return state
            root_menu_items = menu_items(menu)
            main_menu_item = find_sub_menu_item(root_menu_items, 'main')
            main_menu_items = menu_items(cast('Menu', main_menu_item.sub_menu))
            settings_menu_item = find_sub_menu_item(main_menu_items, 'settings')
            settings_menu_items = menu_items(cast('Menu', settings_menu_item.sub_menu))

            category_menu_item = cast(
                'SubMenuItem',
                next(
                    item
                    for item in settings_menu_items
                    if item.label == action.category
                ),
            )

            key = f'{action.service}:'
            if action.key is not None:
                key += action.key

            priorities = {
                **state.settings_items_priorities,
                key: action.priority,
            }

            def sort_key(item: Item) -> tuple[int, str]:
                key_ = item.key or (
                    item.label() if callable(item.label) else item.label
                )
                return (-(priorities.get(key_, 0) or 0), key_)

            if any(
                item.key == key
                for item in cast(
                    'Sequence[Item]',
                    cast('Menu', category_menu_item.sub_menu).items,
                )
            ):
                msg = f"""Settings application with key "{key}", in category \
"{category_menu_item.label}", already exists. Consider providing a unique `key` field \
for the `RegisterSettingAppAction` instance."""
                raise ValueError(msg)

            menu_item = replace(action.menu_item, key=key)
            new_items = sorted(
                [
                    *cast(
                        'Sequence[Item]',
                        cast('Menu', category_menu_item.sub_menu).items,
                    ),
                    menu_item,
                ],
                key=sort_key,
            )

            new_category_menu_item = replace(
                category_menu_item,
                sub_menu=replace(
                    cast('Menu', category_menu_item.sub_menu),
                    items=new_items,
                ),
            )

            new_settings_menu_item = replace(
                settings_menu_item,
                sub_menu=replace(
                    cast('Menu', settings_menu_item.sub_menu),
                    items=[
                        new_category_menu_item if item == category_menu_item else item
                        for item in settings_menu_items
                    ],
                ),
            )

            new_main_menu_item = replace(
                main_menu_item,
                sub_menu=replace(
                    cast('Menu', main_menu_item.sub_menu),
                    items=[
                        new_settings_menu_item if item == settings_menu_item else item
                        for item in main_menu_items
                    ],
                ),
            )

            return replace(
                state,
                settings_items_priorities=priorities,
                menu=replace(
                    menu,
                    items=[
                        new_main_menu_item if item == main_menu_item else item
                        for item in root_menu_items
                    ],
                ),
            )

        case RegisterRegularAppAction():
            menu = state.menu
            if not menu or not action.service:
                return state
            root_menu_items = menu_items(menu)
            main_menu_item = find_sub_menu_item(root_menu_items, 'main')
            main_menu_items = menu_items(cast('Menu', main_menu_item.sub_menu))
            apps_menu_item = find_sub_menu_item(main_menu_items, 'apps')
            apps_menu_items = menu_items(cast('Menu', apps_menu_item.sub_menu))

            key = f'{action.service}:'
            if action.key is not None:
                key += action.key
            if any(item.key == key for item in apps_menu_items):
                msg = f"""Regular application with key "{key}", already exists. \
Consider providing a unique `key` field for the `RegisterRegularAppAction` instance."""
                raise ValueError(msg)

            priorities = {
                **state.apps_items_priorities,
                key: action.priority,
            }

            def sort_key(item: Item) -> tuple[int, str]:
                key_ = item.key or (
                    item.label() if callable(item.label) else item.label
                )
                return (-(priorities.get(key_, 0) or 0), key_)

            menu_item = replace(action.menu_item, key=key)
            new_items = sorted(
                [
                    *cast('Sequence[Item]', apps_menu_items),
                    menu_item,
                ],
                key=sort_key,
            )

            apps_menu_item = replace(
                apps_menu_item,
                sub_menu=replace(
                    cast('Menu', apps_menu_item.sub_menu),
                    items=new_items,
                ),
            )

            main_menu_item = replace(
                main_menu_item,
                sub_menu=replace(
                    cast('Menu', main_menu_item.sub_menu),
                    items=[
                        apps_menu_item if item.key == 'apps' else item
                        for item in main_menu_items
                    ],
                ),
            )

            return replace(
                state,
                menu=replace(
                    menu,
                    items=[
                        main_menu_item if index == 0 else item
                        for index, item in enumerate(root_menu_items)
                    ],
                ),
            )

        case DeregisterRegularAppAction():
            if action.service is None:
                return state
            key = f'{action.service}:'
            if action.key is not None:
                key += action.key

            menu = state.menu
            if not menu:
                return state
            root_menu_items = menu_items(menu)
            main_menu_item = find_sub_menu_item(root_menu_items, 'main')
            main_menu_items = menu_items(cast('Menu', main_menu_item.sub_menu))
            apps_menu_item = find_sub_menu_item(main_menu_items, 'apps')
            apps_menu_items = menu_items(cast('Menu', apps_menu_item.sub_menu))

            new_items = [item for item in apps_menu_items if item.key != key]

            new_apps_menu_item = replace(
                apps_menu_item,
                sub_menu=replace(
                    cast('Menu', apps_menu_item.sub_menu),
                    items=new_items,
                ),
            )

            new_main_menu_item = replace(
                main_menu_item,
                sub_menu=replace(
                    cast('Menu', main_menu_item.sub_menu),
                    items=[
                        new_apps_menu_item if item == apps_menu_item else item
                        for item in main_menu_items
                    ],
                ),
            )

            events: list[MenuGoBackEvent] = []

            if state.path[:3] == ['main', 'apps', key]:
                events = [MenuGoBackEvent()] * (len(state.path) - 2)

            return CompleteReducerResult(
                state=replace(
                    state,
                    menu=replace(
                        menu,
                        items=[
                            new_main_menu_item if item == main_menu_item else item
                            for item in root_menu_items
                        ],
                    ),
                ),
                events=events,
            )

        case SetMenuPathAction():
            return replace(state, path=action.path, depth=action.depth)

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
            menu = state.menu
            if not menu:
                return state
            root_menu_items = menu_items(menu)
            main_menu_item = find_sub_menu_item(root_menu_items, 'main')
            main_menu_items = menu_items(cast('Menu', main_menu_item.sub_menu))
            apps_menu_item = find_sub_menu_item(main_menu_items, 'apps')
            apps_menu_items = menu_items(cast('Menu', apps_menu_item.sub_menu))
            settings_menu_item = find_sub_menu_item(main_menu_items, 'settings')
            settings_menu_items = menu_items(cast('Menu', settings_menu_item.sub_menu))

            new_apps_menu_item = replace(
                apps_menu_item,
                sub_menu=replace(
                    cast('Menu', apps_menu_item.sub_menu),
                    items=[
                        item
                        for item in apps_menu_items
                        if item.key is None
                        or not item.key.startswith(f'{action.service_id}:')
                    ],
                ),
            )

            new_settings_menu_item = replace(
                settings_menu_item,
                sub_menu=replace(
                    cast('Menu', settings_menu_item.sub_menu),
                    items=[
                        replace(
                            category_menu_item,
                            sub_menu=replace(
                                cast('Menu', category_menu_item.sub_menu),
                                items=[
                                    item
                                    for item in menu_items(
                                        cast('Menu', category_menu_item.sub_menu),
                                    )
                                    if item.key is None
                                    or not item.key.startswith(f'{action.service_id}:')
                                ],
                            ),
                        )
                        if isinstance(category_menu_item, SubMenuItem)
                        else category_menu_item
                        for category_menu_item in settings_menu_items
                    ],
                ),
            )

            new_main_menu_item = replace(
                main_menu_item,
                sub_menu=replace(
                    cast('Menu', main_menu_item.sub_menu),
                    items=[
                        new_apps_menu_item
                        if item == apps_menu_item
                        else new_settings_menu_item
                        if item == settings_menu_item
                        else item
                        for item in main_menu_items
                    ],
                ),
            )

            events: list[MenuGoBackEvent] = []

            # Exit open menus of the deregistered app
            if (
                state.path[:2] == ['main', 'apps']
                and len(state.path) > 2  # noqa: PLR2004
                and state.path[2].startswith(
                    f'{action.service_id}:',
                )
            ):
                events = [MenuGoBackEvent()] * (len(state.path) - 2)
            if (
                state.path[:2] == ['main', 'settings']
                and len(state.path) > 3  # noqa: PLR2004
                and state.path[3].startswith(
                    f'{action.service_id}:',
                )
            ):
                events = [MenuGoBackEvent()] * (len(state.path) - 3)

            return CompleteReducerResult(
                state=replace(
                    state,
                    menu=replace(
                        menu,
                        items=[
                            new_main_menu_item if item == main_menu_item else item
                            for item in root_menu_items
                        ],
                    ),
                ),
                events=events,
            )

        case UpdateCurrentViewAction():
            # Update current_view with a computed view (used by dynamic menu system)
            # This allows ViewRenderer to push computed views that include dynamic menus
            if state.current_view == action.view:
                return state  # No change
            return CompleteReducerResult(
                state=replace(state, current_view=action.view),
                events=[ViewChangedEvent(view=action.view)],
            )

        case ExecuteMenuActionAction():
            # Execute a menu action by its action_id
            # This is handled synchronously - the handler may dispatch other actions
            from ubo_app.store.core.action_registry import execute_action

            execute_action(action.action_id)
            return state

        case _:
            return state
