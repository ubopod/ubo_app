# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import replace
from typing import Sequence, cast

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)
from ubo_gui.menu.types import Item, Menu, SubMenuItem, menu_items

from ubo_app.store.main import (
    InitEvent,
    MainAction,
    MainState,
    PowerOffAction,
    PowerOffEvent,
    RegisterAppAction,
    RegisterRegularAppAction,
    SetMenuPathAction,
)
from ubo_app.store.services.keypad import (
    Key,
    KeypadEvent,
    KeypadKeyPressAction,
    KeypadKeyPressEvent,
)
from ubo_app.store.services.sound import SoundChangeVolumeAction, SoundDevice


def reducer(  # noqa: C901
    state: MainState | None,
    action: MainAction,
) -> ReducerResult[
    MainState,
    SoundChangeVolumeAction,
    KeypadEvent | InitEvent | PowerOffEvent,
]:
    if state is None:
        if isinstance(action, InitAction):
            from ._menus import HOME_MENU

            return CompleteReducerResult(
                state=MainState(menu=HOME_MENU),
                events=[InitEvent()],
            )
        raise InitializationActionError(action)

    if isinstance(action, KeypadKeyPressAction):
        actions: list[SoundChangeVolumeAction] = []
        if action.key == Key.UP and len(state.path) == 1:
            actions.append(
                SoundChangeVolumeAction(
                    amount=0.05,
                    device=SoundDevice.OUTPUT,
                ),
            )
        if action.key == Key.DOWN and len(state.path) == 1:
            actions.append(
                SoundChangeVolumeAction(
                    amount=-0.05,
                    device=SoundDevice.OUTPUT,
                ),
            )
        return CompleteReducerResult(
            state=state,
            actions=actions,
            events=[
                KeypadKeyPressEvent(key=action.key),
            ],
        )

    if isinstance(action, RegisterAppAction):
        menu = state.menu
        parent_index = 0 if isinstance(action, RegisterRegularAppAction) else 1

        if not menu:
            return state

        root_menu_items = menu_items(menu)

        main_menu_item: Item = root_menu_items[0]
        if not isinstance(main_menu_item, SubMenuItem):
            msg = 'Main menu item is not a `SubMenuItem`'
            raise TypeError(msg)

        main_menu_items = menu_items(cast(Menu, main_menu_item.sub_menu))

        desired_menu_item = main_menu_items[parent_index]
        if not isinstance(desired_menu_item, SubMenuItem):
            menu_title = (
                'Applications'
                if isinstance(action, RegisterRegularAppAction)
                else 'Settings'
            )
            msg = f'{menu_title} menu item is not a `SubMenuItem`'
            raise TypeError(msg)

        new_items = [
            *cast(Sequence[Item], cast(Menu, desired_menu_item.sub_menu).items),
            action.menu_item,
        ]
        desired_menu_item = replace(
            desired_menu_item,
            sub_menu=replace(
                cast(Menu, desired_menu_item.sub_menu),
                items=new_items,
            ),
        )
        main_menu_item = replace(
            main_menu_item,
            sub_menu=replace(
                cast(Menu, main_menu_item.sub_menu),
                items=[
                    desired_menu_item if index == parent_index else item
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
        return replace(state, path=action.path)

    if isinstance(action, PowerOffAction):
        return CompleteReducerResult(
            state=state,
            events=[PowerOffEvent()],
        )

    return state
