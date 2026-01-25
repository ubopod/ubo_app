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
    CloseApplicationAction,
    CloseApplicationEvent,
    DeregisterRegularAppAction,
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
    NotificationStackItem,
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
        try:
            sub_item = find_sub_menu_item(items, item.menu_key)
            sub_menu = sub_item.sub_menu
            current_menu = sub_menu() if callable(sub_menu) else sub_menu
        except (TypeError, StopIteration):
            # Menu key not found or not a submenu
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
            return CompleteReducerResult(
                state=replace(
                    state,
                    stack=new_stack,
                    path=new_path,
                    depth=len(new_stack),
                ),
                events=[StackChangedEvent(stack=new_stack)],
            )

        case StackPushApplicationAction():
            new_item = ApplicationStackItem(
                id=uuid.uuid4().hex,
                application_id=action.application_id,
                initialization_args=action.initialization_args,
                initialization_kwargs=action.initialization_kwargs,
            )
            new_stack = (*state.stack, new_item)
            return CompleteReducerResult(
                state=replace(
                    state,
                    stack=new_stack,
                    depth=len(new_stack),
                ),
                events=[StackChangedEvent(stack=new_stack)],
            )

        case StackPushNotificationAction():
            new_item = NotificationStackItem(
                id=uuid.uuid4().hex,
                notification_id=action.notification_id,
            )
            new_stack = (*state.stack, new_item)
            return CompleteReducerResult(
                state=replace(
                    state,
                    stack=new_stack,
                    depth=len(new_stack),
                ),
                events=[StackChangedEvent(stack=new_stack)],
            )

        case StackPopAction():
            if len(state.stack) <= 1:
                return state  # Can't pop root
            # Pop 'count' items but always keep at least root
            pop_count = min(action.count, len(state.stack) - 1)
            new_stack = state.stack[:-pop_count] if pop_count > 0 else state.stack
            new_path = derive_path_from_stack(new_stack)
            return CompleteReducerResult(
                state=replace(
                    state,
                    stack=new_stack,
                    path=new_path,
                    depth=len(new_stack),
                ),
                events=[StackChangedEvent(stack=new_stack)],
            )

        case StackPopToRootAction():
            if len(state.stack) <= 1:
                return state  # Already at root
            new_stack = state.stack[:1]
            return CompleteReducerResult(
                state=replace(
                    state,
                    stack=new_stack,
                    path=[],
                    depth=1,
                ),
                events=[StackChangedEvent(stack=new_stack)],
            )

        case StackPopItemAction():
            # Find and remove the specific item from stack
            new_stack = tuple(
                item for item in state.stack if item.id != action.item_id
            )
            if new_stack == state.stack:
                return state  # Item not found, no change
            new_path = derive_path_from_stack(new_stack)
            return CompleteReducerResult(
                state=replace(
                    state,
                    stack=new_stack,
                    path=new_path,
                    depth=len(new_stack),
                ),
                events=[StackChangedEvent(stack=new_stack)],
            )

        case StackSetPageIndexAction():
            if not state.stack:
                return state
            top = state.stack[-1]
            if not isinstance(top, MenuStackItem):
                return state  # Can only set page index for menu items
            new_top = replace(top, page_index=action.page_index)
            new_stack = (*state.stack[:-1], new_top)
            return CompleteReducerResult(
                state=replace(state, stack=new_stack),
                events=[StackPageIndexChangedEvent(page_index=action.page_index)],
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

        case _:
            return state
