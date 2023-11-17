# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from redux import BaseAction, BaseState, InitAction, InitializationActionError

from ubo_app.store.keypad import Key, KeypadAction

from ._menus import HOME_MENU

if TYPE_CHECKING:
    from typing_extensions import TypeAlias
    from ubo_gui.menu.types import Menu


@dataclass(frozen=True)
class MainState(BaseState):
    menu: Menu
    page: int
    path: list[int]


@dataclass(frozen=True)
class SelectAction(BaseAction):
    type: Literal['MAIN_SELECT'] = 'MAIN_SELECT'


MainAction: TypeAlias = InitAction | KeypadAction


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

    return state
