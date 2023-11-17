# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import math
from dataclasses import replace
from functools import reduce
from typing import TYPE_CHECKING

from ubo_gui.menu import PAGE_SIZE

from . import autorun

if TYPE_CHECKING:
    from ubo_gui.menu import Item, Menu

    from ubo_app.store.main import MainState


@autorun(lambda state: (state.main.path, state.main.menu))
def current_menu(values: tuple[list[int], Menu]) -> Menu:
    path, menu = values
    return reduce(
        lambda menu, index: menu['items'][index]['sub_menu'],
        path,
        menu,
    )


@autorun(lambda _: current_menu())
def current_menu_items(menu: Menu) -> Item:
    items = menu['items']
    if callable(items):
        items = items()
    return items


@autorun(lambda _: current_menu_items())
def current_menu_pages_count(menu: Menu) -> int:
    count = len(current_menu_items())
    if 'heading' in menu:
        count += 2
    return math.ceil(count / 3)


def select(state: MainState, index: int) -> MainState:
    index = index + state.page * PAGE_SIZE
    if 'heading' in current_menu():
        index -= 2
    return replace(state, path=[*state.path, index])
