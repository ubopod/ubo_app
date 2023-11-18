# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from redux import BaseState, InitAction, InitializationActionError
from ubo_gui.menu import Item, is_sub_menu_item, menu_items

from ubo_app.store.app import RegisterAppAction
from ubo_app.store.keypad import Key, KeypadAction

from ._menus import HOME_MENU

if TYPE_CHECKING:
    from typing_extensions import TypeAlias
    from ubo_gui.menu.types import Menu
    from ubo_gui.page import PageWidget


@dataclass(frozen=True)
class MainState(BaseState):
    menu: Menu
    page: int
    path: list[int]
    current_application: PageWidget | None = None


MainAction: TypeAlias = InitAction | KeypadAction | RegisterAppAction


def main_reducer(state: MainState | None, action: MainAction) -> MainState:
    if state is None:
        if action.type == 'INIT':
            return MainState(path=[], page=0, menu=HOME_MENU)
        raise InitializationActionError

    from ubo_app.store.main_selectors import current_menu_pages_count, select

    if action.type == 'KEYPAD_KEY_PRESS':
        if action.payload.key == Key.L1:
            return select(state, 0)
        if action.payload.key == Key.L2:
            return select(state, 1)
        if action.payload.key == Key.L3:
            return select(state, 2)
        if action.payload.key == Key.BACK:
            return replace(state, path=state.path[:-1])
        if action.payload.key == Key.DOWN:
            return replace(state, page=(state.page + 1) % current_menu_pages_count())
        if action.payload.key == Key.UP:
            return replace(state, page=(state.page - 1) % current_menu_pages_count())
    elif action.type in ('MAIN_REGISTER_REGULAR_APP', 'MAIN_REGISTER_SETTING_APP'):
        # TODO(sassanh): clone the menu
        # menu = copy.deepcopy(state.menu)
        menu = state.menu

        main_menu_item: Item = menu_items(menu)[0]
        if not is_sub_menu_item(main_menu_item):
            msg = 'Main menu item is not a `SubMenuItem`'
            raise TypeError(msg)

        container_menu_item: Item
        if action.type == 'MAIN_REGISTER_REGULAR_APP':
            container_menu_item = menu_items(main_menu_item['sub_menu'])[0]
        else:
            container_menu_item = menu_items(main_menu_item['sub_menu'])[1]

        if not is_sub_menu_item(container_menu_item):
            msg = 'Settings menu item is not a `SubMenuItem`'
            raise TypeError(msg)

        menu_items(container_menu_item['sub_menu']).append(
            action.payload.menu_item,
        )
        return replace(state, menu=menu)

    return state
