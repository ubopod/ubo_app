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

from ubo_app.store.core import (
    InitEvent,
    MainAction,
    MainState,
    PowerEvent,
    PowerOffAction,
    PowerOffEvent,
    RebootAction,
    RebootEvent,
    RegisterRegularAppAction,
    RegisterSettingAppAction,
    SetMenuPathAction,
)
from ubo_app.store.services.audio import AudioChangeVolumeAction, AudioDevice
from ubo_app.store.services.keypad import (
    Key,
    KeypadEvent,
    KeypadKeyPressAction,
    KeypadKeyPressEvent,
    KeypadKeyReleaseAction,
    KeypadKeyReleaseEvent,
)


def reducer(
    state: MainState | None,
    action: MainAction,
) -> ReducerResult[
    MainState,
    AudioChangeVolumeAction,
    KeypadEvent | InitEvent | PowerEvent,
]:
    from ubo_gui.menu.types import Item, Menu, SubMenuItem, menu_items

    if state is None:
        if isinstance(action, InitAction):
            from ._menus import HOME_MENU

            return CompleteReducerResult(
                state=MainState(menu=HOME_MENU),
                events=[InitEvent()],
            )
        raise InitializationActionError(action)

    if isinstance(action, KeypadKeyPressAction):
        actions: list[AudioChangeVolumeAction] = []
        events: list[KeypadKeyPressEvent] = []
        if action.key == Key.UP and state.depth == 1:
            actions = [
                AudioChangeVolumeAction(
                    amount=0.05,
                    device=AudioDevice.OUTPUT,
                ),
            ]
        elif action.key == Key.DOWN and state.depth == 1:
            actions = [
                AudioChangeVolumeAction(
                    amount=-0.05,
                    device=AudioDevice.OUTPUT,
                ),
            ]
        else:
            events = [KeypadKeyPressEvent(key=action.key, time=action.time)]
        return CompleteReducerResult(state=state, actions=actions, events=events)
    if isinstance(action, KeypadKeyReleaseAction):
        return CompleteReducerResult(
            state=state,
            events=[KeypadKeyReleaseEvent(key=action.key, time=action.time)],
        )

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

        label = (
            action.menu_item.label()
            if callable(action.menu_item.label)
            else action.menu_item.label
        )

        priorities = {
            **state.settings_items_priorities,
            label: action.priority,
        }

        def sort_key(item: Item) -> tuple[int, str]:
            label = item.label() if callable(item.label) else item.label
            return (-(priorities.get(label, 0) or 0), label)

        key = action.service
        if action.key is not None:
            key += f':{action.key}'
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
        main_menu_item: Item = root_menu_items[0]

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

        menu_item = replace(action.menu_item, key=key)
        new_items = sorted(
            [
                *cast(Sequence[Item], cast(Menu, apps_menu_item.sub_menu).items),
                menu_item,
            ],
            key=lambda item: item.label() if callable(item.label) else item.label,
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

    if isinstance(action, SetMenuPathAction):
        return replace(state, path=action.path, depth=action.depth)

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
