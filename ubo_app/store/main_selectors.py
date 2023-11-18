# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import math
from dataclasses import replace
from functools import reduce
from typing import TYPE_CHECKING

from ubo_gui.menu import PAGE_SIZE, is_sub_menu_item, menu_items

from . import autorun

if TYPE_CHECKING:
    from ubo_gui.menu.types import Item, Menu

    from ubo_app.store.main import MainState


@autorun(lambda state: (state.main.path, state.main.menu))
def current_menu(selector_result: tuple[list[int], Menu]) -> Menu:
    path, menu = selector_result

    def reducer(menu: Menu, index: int) -> Menu:
        item = menu_items(menu)[index]

        if is_sub_menu_item(item):
            return item['sub_menu']

        msg = 'Menu is not `SubMenuItem`'
        raise TypeError(msg)

    return reduce(reducer, path, menu)


@autorun(lambda _: current_menu())
def current_menu_pages_count(selector_result: Menu) -> int:
    menu = selector_result
    items = menu_items(menu)
    count = len(items)
    if 'heading' in menu:
        count += 2
    return math.ceil(count / 3)


def select(state: MainState, index: int) -> MainState:
    index = index + state.page * PAGE_SIZE
    if 'heading' in current_menu():
        index -= 2
    return replace(state, path=[*state.path, index])
