# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import field, replace
from typing import TYPE_CHECKING, Sequence, cast

from redux import (
    BaseAction,
    BaseEvent,
    CompleteReducerResult,
    FinishAction,
    Immutable,
    InitAction,
    InitializationActionError,
    ReducerResult,
)
from ubo_gui.menu.types import SubMenuItem

from ubo_app.store.app import (
    RegisterAppAction,
    RegisterRegularAppAction,
)
from ubo_app.store.keypad import (
    Key,
    KeypadAction,
    KeypadEvent,
    KeypadKeyPressAction,
    KeypadKeyPressEvent,
)
from ubo_app.store.sound import (
    SoundChangeVolumeAction,
    SoundDevice,
)
from ubo_app.store.status_icons import IconAction

if TYPE_CHECKING:
    from typing_extensions import TypeAlias
    from ubo_gui.menu.types import Menu


class MainState(Immutable):
    menu: Menu | None = None
    path: Sequence[int] = field(default_factory=list)


class InitEvent(BaseEvent):
    ...


class SetMenuPathAction(BaseAction):
    path: Sequence[str]


MainAction: TypeAlias = (
    InitAction
    | FinishAction
    | IconAction
    | KeypadAction
    | RegisterAppAction
    | SetMenuPathAction
)


def main_reducer(  # noqa: C901
    state: MainState | None,
    action: MainAction,
) -> ReducerResult[MainState, SoundChangeVolumeAction, KeypadEvent | InitEvent]:
    if state is None:
        if isinstance(action, InitAction):
            from ._menus import HOME_MENU

            return CompleteReducerResult(
                state=MainState(menu=HOME_MENU),
                events=[InitEvent()],
            )
        raise InitializationActionError(action)

    if isinstance(action, KeypadKeyPressAction):
        actions = []
        if action.key == Key.UP and len(state.path) == 0:
            actions.append(
                SoundChangeVolumeAction(
                    amount=0.05,
                    device=SoundDevice.OUTPUT,
                ),
            )
        if action.key == Key.DOWN and len(state.path) == 0:
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
        from ubo_gui.menu import Item, menu_items

        menu = state.menu
        parent_index = 0 if isinstance(action, RegisterRegularAppAction) else 1

        if not menu:
            return state

        root_menu_items = menu_items(menu)

        main_menu_item: Item = root_menu_items[0]
        if not isinstance(main_menu_item, SubMenuItem):
            msg = 'Main menu item is not a `SubMenuItem`'
            raise TypeError(msg)

        main_menu_items = menu_items(main_menu_item.sub_menu)

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
            *cast(Sequence[Item], desired_menu_item.sub_menu.items),
            action.menu_item,
        ]
        desired_menu_item = replace(
            desired_menu_item,
            sub_menu=replace(
                desired_menu_item.sub_menu,
                items=new_items,
            ),
        )
        main_menu_item = replace(
            main_menu_item,
            sub_menu=replace(
                main_menu_item.sub_menu,
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

    return state
