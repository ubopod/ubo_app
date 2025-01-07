# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import cast

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.core.types import (
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
    StoreRecordedSequenceEvent,
    ToggleRecordingAction,
)


def reducer(
    state: MainState | None,
    action: MainAction,
) -> ReducerResult[MainState, None, InitEvent | MainEvent]:
    from ubo_gui.menu.types import Item, Menu, SubMenuItem, menu_items

    if state is None:
        if isinstance(action, InitAction):
            from .menus import HOME_MENU

            return CompleteReducerResult(
                state=MainState(menu=HOME_MENU),
                events=[InitEvent()],
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

    if isinstance(action, MenuGoBackAction):
        return CompleteReducerResult(
            state=state,
            events=[MenuGoBackEvent()],
        )

    if isinstance(action, MenuGoHomeAction):
        return CompleteReducerResult(
            state=state,
            events=[MenuGoHomeEvent()],
        )

    if isinstance(action, MenuChooseByIconAction):
        return CompleteReducerResult(
            state=state,
            events=[MenuChooseByIconEvent(icon=action.icon)],
        )

    if isinstance(action, MenuChooseByLabelAction):
        return CompleteReducerResult(
            state=state,
            events=[MenuChooseByLabelEvent(label=action.label)],
        )

    if isinstance(action, MenuChooseByIndexAction):
        return CompleteReducerResult(
            state=state,
            events=[MenuChooseByIndexEvent(index=action.index)],
        )
    if isinstance(action, MenuScrollAction):
        return CompleteReducerResult(
            state=state,
            events=[MenuScrollEvent(direction=action.direction)],
        )

    if isinstance(action, OpenApplicationAction):
        return CompleteReducerResult(
            state=state,
            events=[OpenApplicationEvent(application=action.application)],
        )

    if isinstance(action, CloseApplicationAction):
        return CompleteReducerResult(
            state=state,
            events=[CloseApplicationEvent(application=action.application)],
        )

    if isinstance(action, ToggleRecordingAction) and not state.is_replaying:
        return CompleteReducerResult(
            state=replace(
                state,
                is_recording=not state.is_recording,
                recorded_sequence=[],
            ),
            events=[
                StoreRecordedSequenceEvent(recorded_sequence=state.recorded_sequence),
            ]
            if state.is_recording
            else [],
        )

    if (
        isinstance(action, ReplayRecordedSequenceAction)
        and not state.is_recording
        and not state.is_replaying
    ):
        return CompleteReducerResult(
            state=replace(state, is_replaying=True),
            events=[ReplayRecordedSequenceEvent()],
        )

    if isinstance(action, ReportReplayingDoneAction):
        return replace(state, is_replaying=False)

    if isinstance(action, RegisterSettingAppAction):
        parent_index = 1
        menu = state.menu
        if not menu:
            return state
        root_menu_items = menu_items(menu)
        main_menu_item = cast(SubMenuItem, root_menu_items[0])
        main_menu_items = menu_items(cast(Menu, main_menu_item.sub_menu))

        settings_menu_item = cast(SubMenuItem, main_menu_items[parent_index])
        settings_menu_items = menu_items(cast(Menu, settings_menu_item.sub_menu))

        category_menu_item = cast(
            SubMenuItem,
            next(item for item in settings_menu_items if item.label == action.category),
        )

        key = action.service
        if action.key is not None:
            key += f':{action.key}'

        priorities = {
            **state.settings_items_priorities,
            key: action.priority,
        }

        def sort_key(item: Item) -> tuple[int, str]:
            key = item.key or (item.label() if callable(item.label) else item.label)
            return (-(priorities.get(key, 0) or 0), key)

        if any(
            item.key == key
            for item in cast(
                Sequence[Item],
                cast(Menu, category_menu_item.sub_menu).items,
            )
        ):
            msg = f"""Settings application with key "{key}", in category \
"{category_menu_item.label}", already exists. Consider providing a unique `key` field \
for the `RegisterSettingAppAction` instance."""
            raise ValueError(msg)

        menu_item = replace(action.menu_item, key=key)
        new_items = sorted(
            [
                *cast(Sequence[Item], cast(Menu, category_menu_item.sub_menu).items),
                menu_item,
            ],
            key=sort_key,
        )

        new_category_menu_item = replace(
            category_menu_item,
            sub_menu=replace(
                cast(Menu, category_menu_item.sub_menu),
                items=new_items,
            ),
        )

        new_settings_menu_item = replace(
            settings_menu_item,
            sub_menu=replace(
                cast(Menu, settings_menu_item.sub_menu),
                items=[
                    new_category_menu_item if item == category_menu_item else item
                    for item in settings_menu_items
                ],
            ),
        )

        new_main_menu_item = replace(
            main_menu_item,
            sub_menu=replace(
                cast(Menu, main_menu_item.sub_menu),
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

    if isinstance(action, RegisterRegularAppAction):
        parent_index = 0
        menu = state.menu
        if not menu:
            return state
        root_menu_items = menu_items(menu)
        main_menu_item = root_menu_items[0]

        if not isinstance(main_menu_item, SubMenuItem):
            msg = 'Main menu item is not a `SubMenuItem`'
            raise TypeError(msg)

        main_menu_items = menu_items(cast(Menu, main_menu_item.sub_menu))

        apps_menu_item = main_menu_items[parent_index]

        if not isinstance(apps_menu_item, SubMenuItem):
            msg = 'Applications menu item is not a `SubMenuItem`'
            raise TypeError(msg)

        key = action.service
        if action.key is not None:
            key += f':{action.key}'
        if any(
            item.key == key
            for item in cast(
                Sequence[Item],
                cast(Menu, apps_menu_item.sub_menu).items,
            )
        ):
            msg = f"""Regular application with key "{key}", already exists. Consider \
providing a unique `key` field for the `RegisterRegularAppAction` instance."""
            raise ValueError(msg)

        priorities = {
            **state.apps_items_priorities,
            key: action.priority,
        }

        def sort_key(item: Item) -> tuple[int, str]:
            key = item.key or (item.label() if callable(item.label) else item.label)
            return (-(priorities.get(key, 0) or 0), key)

        menu_item = replace(action.menu_item, key=key)
        new_items = sorted(
            [
                *cast(Sequence[Item], cast(Menu, apps_menu_item.sub_menu).items),
                menu_item,
            ],
            key=sort_key,
        )

        apps_menu_item = replace(
            apps_menu_item,
            sub_menu=replace(
                cast(Menu, apps_menu_item.sub_menu),
                items=new_items,
            ),
        )

        main_menu_item = replace(
            main_menu_item,
            sub_menu=replace(
                cast(Menu, main_menu_item.sub_menu),
                items=[
                    apps_menu_item if index == parent_index else item
                    for index, item in enumerate(main_menu_items)
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

    if isinstance(action, DeregisterRegularAppAction):
        key = action.service
        if action.key is not None:
            key += f':{action.key}'

        if key is None:
            return state

        parent_index = 0
        menu = state.menu
        if not menu:
            return state
        root_menu_items = menu_items(menu)
        main_menu_item = root_menu_items[0]

        if not isinstance(main_menu_item, SubMenuItem):
            msg = 'Main menu item is not a `SubMenuItem`'
            raise TypeError(msg)

        main_menu_items = menu_items(cast(Menu, main_menu_item.sub_menu))

        apps_menu_item = main_menu_items[parent_index]

        if not isinstance(apps_menu_item, SubMenuItem):
            msg = 'Applications menu item is not a `SubMenuItem`'
            raise TypeError(msg)

        apps_menu_items = menu_items(cast(Menu, apps_menu_item.sub_menu))

        new_items = [item for item in apps_menu_items if item.key != key]

        new_apps_menu_item = replace(
            apps_menu_item,
            sub_menu=replace(
                cast(Menu, apps_menu_item.sub_menu),
                items=new_items,
            ),
        )

        new_main_menu_item = replace(
            main_menu_item,
            sub_menu=replace(
                cast(Menu, main_menu_item.sub_menu),
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

    if isinstance(action, SetMenuPathAction):
        return replace(state, path=action.path, depth=action.depth)

    if isinstance(action, SetAreEnclosuresVisibleAction):
        return replace(
            state,
            is_header_visible=action.is_header_visible,
            is_footer_visible=action.is_footer_visible,
        )

    if isinstance(action, PowerOffAction):
        return CompleteReducerResult(
            state=state,
            events=[PowerOffEvent()],
        )

    if isinstance(action, RebootAction):
        return CompleteReducerResult(
            state=state,
            events=[RebootEvent()],
        )

    return state
